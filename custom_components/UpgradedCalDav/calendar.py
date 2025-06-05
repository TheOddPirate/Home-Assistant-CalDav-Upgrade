"""Support for WebDav Calendar."""

from __future__ import annotations

from datetime import datetime, timezone
import logging

import caldav
import voluptuous as vol

from homeassistant.components.calendar import (
    ENTITY_ID_FORMAT,
    PLATFORM_SCHEMA as CALENDAR_PLATFORM_SCHEMA,
    CalendarEntity,
    CalendarEvent,
    CalendarEntityFeature,
    is_offset_reached,
    EVENT_START,
    EVENT_END,
    EVENT_SUMMARY,
    EVENT_DESCRIPTION,
    EVENT_LOCATION,
    EVENT_RRULE,
    EVENT_UID,
    EVENT_RECURRENCE_ID,
    EVENT_RECURRENCE_RANGE,
)
from .const import (
    CONF_NAME,
    CONF_PASSWORD,
    CONF_URL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity import async_generate_entity_id
from homeassistant.helpers.entity_platform import (
    AddConfigEntryEntitiesCallback,
    AddEntitiesCallback,
)
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util
from homeassistant.exceptions import HomeAssistantError
from homeassistant.components.calendar import EVENT_START, EVENT_END, EVENT_SUMMARY, EVENT_DESCRIPTION, EVENT_LOCATION, EVENT_RRULE
import vobject
from datetime import date
from zoneinfo import ZoneInfo
from . import CalDavConfigEntry
from .api import async_get_calendars, get_attr_value
from .coordinator import CalDavUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

CONF_CALENDARS = "calendars"
CONF_CUSTOM_CALENDARS = "custom_calendars"
CONF_CALENDAR = "calendar"
CONF_SEARCH = "search"
CONF_DAYS = "days"


# Number of days to look ahead for next event when configured by ConfigEntry
CONFIG_ENTRY_DEFAULT_DAYS = 7

# Only allow VCALENDARs that support this component type
SUPPORTED_COMPONENT = "VEVENT"

PLATFORM_SCHEMA = CALENDAR_PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_URL): vol.Url(),
        vol.Optional(CONF_CALENDARS, default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Inclusive(CONF_USERNAME, "authentication"): cv.string,
        vol.Inclusive(CONF_PASSWORD, "authentication"): cv.string,
        vol.Optional(CONF_CUSTOM_CALENDARS, default=[]): vol.All(
            cv.ensure_list,
            [
                vol.Schema(
                    {
                        vol.Required(CONF_CALENDAR): cv.string,
                        vol.Required(CONF_NAME): cv.string,
                        vol.Required(CONF_SEARCH): cv.string,
                    }
                )
            ],
        ),
        vol.Optional(CONF_VERIFY_SSL, default=True): cv.boolean,
        vol.Optional(CONF_DAYS, default=1): cv.positive_int,
    }
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    disc_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the WebDav Calendar platform."""
    url = config[CONF_URL]
    username = config.get(CONF_USERNAME)
    password = config.get(CONF_PASSWORD)
    days = config[CONF_DAYS]

    client = caldav.DAVClient(
        url, None, username, password, ssl_verify_cert=config[CONF_VERIFY_SSL]
    )

    calendars = await async_get_calendars(hass, client, SUPPORTED_COMPONENT)

    entities = []
    device_id: str | None
    for calendar in list(calendars):
        # If a calendar name was given in the configuration,
        # ignore all the others
        if config[CONF_CALENDARS] and calendar.name not in config[CONF_CALENDARS]:
            _LOGGER.debug("Ignoring calendar '%s'", calendar.name)
            continue

        # Create additional calendars based on custom filtering rules
        for cust_calendar in config[CONF_CUSTOM_CALENDARS]:
            # Check that the base calendar matches
            if cust_calendar[CONF_CALENDAR] != calendar.name:
                continue

            name = cust_calendar[CONF_NAME]
            device_id = f"{cust_calendar[CONF_CALENDAR]} {cust_calendar[CONF_NAME]}"
            entity_id = async_generate_entity_id(ENTITY_ID_FORMAT, device_id, hass=hass)
            coordinator = CalDavUpdateCoordinator(
                hass,
                None,
                calendar=calendar,
                days=days,
                include_all_day=True,
                search=cust_calendar[CONF_SEARCH],
            )
            entities.append(
                WebDavCalendarEntity(name, entity_id, coordinator, supports_offset=True)
            )

        # Create a default calendar if there was no custom one for all calendars
        # that support events.
        if not config[CONF_CUSTOM_CALENDARS]:
            name = calendar.name
            device_id = calendar.name
            entity_id = async_generate_entity_id(ENTITY_ID_FORMAT, device_id, hass=hass)
            coordinator = CalDavUpdateCoordinator(
                hass,
                None,
                calendar=calendar,
                days=days,
                include_all_day=False,
                search=None,
            )
            entities.append(
                WebDavCalendarEntity(name, entity_id, coordinator, supports_offset=True)
            )

    async_add_entities(entities, True)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CalDavConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the CalDav calendar platform for a config entry."""
    calendars = await async_get_calendars(hass, entry.runtime_data, SUPPORTED_COMPONENT)
    async_add_entities(
        (
            WebDavCalendarEntity(
                calendar.name,
                async_generate_entity_id(ENTITY_ID_FORMAT, calendar.name, hass=hass),
                CalDavUpdateCoordinator(
                    hass,
                    entry,
                    calendar=calendar,
                    days=CONFIG_ENTRY_DEFAULT_DAYS,
                    include_all_day=True,
                    search=None,
                ),
                unique_id=f"{entry.entry_id}-{calendar.id}",
            )
            for calendar in calendars
            if calendar.name
        ),
        True,
    )


class WebDavCalendarEntity(CoordinatorEntity[CalDavUpdateCoordinator], CalendarEntity):
    """A device for getting the next Task from a WebDav Calendar."""

    def __init__(
        self,
        name: str | None,
        entity_id: str,
        coordinator: CalDavUpdateCoordinator,
        unique_id: str | None = None,
        supports_offset: bool = False,
    ) -> None:
        """Create the WebDav Calendar Event Device."""
        super().__init__(coordinator)
        self.entity_id = entity_id
        self._event: CalendarEvent | None = None
        self._attr_name = name
        if unique_id is not None:
            self._attr_unique_id = unique_id
        self._supports_offset = supports_offset
        # Legg til støtte for både CREATE og UPDATE
        self._attr_supported_features = (
            CalendarEntityFeature.CREATE_EVENT |
            CalendarEntityFeature.UPDATE_EVENT |
            CalendarEntityFeature.DELETE_EVENT
        )

    @property
    def event(self) -> CalendarEvent | None:
        """Return the next upcoming event."""
        return self._event

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Get all events in a specific time frame."""
        return await self.coordinator.async_get_events(hass, start_date, end_date)

    # Add new method for creating events
    async def async_create_event(self, **kwargs: Any) -> None:
        """Add a new event to calendar."""
        try:
            dtstart = kwargs[EVENT_START]
            dtend = kwargs[EVENT_END]

            # Convert to local time if datetime
            if isinstance(dtstart, datetime):
                dtstart = dt_util.as_local(dtstart)
            elif isinstance(dtstart, date):
                dtstart = datetime.combine(dtstart, datetime.min.time())
                dtstart = dt_util.as_local(dtstart)

            if isinstance(dtend, datetime):
                dtend = dt_util.as_local(dtend)
            elif isinstance(dtend, date):
                dtend = datetime.combine(dtend, datetime.min.time())
                dtend = dt_util.as_local(dtend)

            def create_event():
                event_data = {
                    "summary": kwargs[EVENT_SUMMARY],
                    "dtstart": dtstart,
                    "dtend": dtend,
                }

                if description := kwargs.get(EVENT_DESCRIPTION):
                    event_data["description"] = description or " "
                if location := kwargs.get(EVENT_LOCATION):
                    event_data["location"] = location  or " "
                if rrule := kwargs.get(EVENT_RRULE):
                    # Parse RRULE and add components individually
                    rrule_parts = dict(part.split('=') for part in rrule.split(';'))
                    event_data["rrule"] = {
                        "freq": rrule_parts["FREQ"],
                        "count": int(rrule_parts["COUNT"]) if "COUNT" in rrule_parts else None
                    }

                # Let the library handle the iCal creation
                return self.coordinator.calendar.save_event(**event_data)

            await self.hass.async_add_executor_job(create_event)
            _LOGGER.info(
                "Successfully created event: %s from %s to %s", 
                kwargs[EVENT_SUMMARY], dtstart, dtend
            )
            if EVENT_RRULE in kwargs:
                _LOGGER.info("Event created with recurrence rule: %s", kwargs[EVENT_RRULE])
            
            await self.coordinator.async_refresh()
            
        except Exception as err:
            _LOGGER.error("Error creating calendar event: %s", err)
            raise HomeAssistantError(f"Error creating calendar event: {err}") from err

    async def async_delete_event(
        self,
        uid: str,
        recurrence_id: datetime | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        """Delete an event."""
        try:
            def delete_event():
                events = self.coordinator.calendar.search(
                    event=True,
                    uid=uid
                )
                if not events:
                    _LOGGER.error("No event found with UID: %s", uid)
                    return
                events[0].delete()

            await self.hass.async_add_executor_job(delete_event)
            await self.coordinator.async_refresh()
        except Exception as err:
            _LOGGER.error("Error deleting calendar event: %s", err)
            raise

    async def async_update_event(
        self,
        uid: str,
        event: dict[str, Any],
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        """Update an event on the calendar."""
        try:
            def update_event():
                _LOGGER.debug("Attempting to update event with UID: %s", uid)
                events = self.coordinator.calendar.search(event=True, uid=uid)
                if not events:
                    raise HomeAssistantError(f"No event found with UID: {uid}")
                
                caldav_event = events[0]
                cal = caldav_event.instance
                vevent = cal.vevent

                # Update standard properties
                if EVENT_SUMMARY in event:
                    vevent.summary.value = event[EVENT_SUMMARY]
                if EVENT_START in event:
                    vevent.dtstart.value = event[EVENT_START]
                if EVENT_END in event:
                    vevent.dtend.value = event[EVENT_END]
                if EVENT_DESCRIPTION in event:
                    if hasattr(vevent, "description"):
                        vevent.description.value = event[EVENT_DESCRIPTION]
                    else:
                        vevent.add("description").value = event[EVENT_DESCRIPTION]
                if EVENT_LOCATION in event:
                    if hasattr(vevent, "location"):
                        vevent.location.value = event[EVENT_LOCATION]
                    else:
                        vevent.add("location").value = event[EVENT_LOCATION]

                # Handle recurrence updates
                if EVENT_RRULE in event:
                    rrule = event[EVENT_RRULE]
                    if rrule:
                        # If there's a recurrence rule
                        if hasattr(vevent, "rrule"):
                            vevent.rrule.value = rrule
                        else:
                            vevent.add("rrule").value = rrule
                        _LOGGER.debug("Updated RRULE to: %s", rrule)
                    elif hasattr(vevent, "rrule"):
                        # If there's no recurrence rule but the event had one, remove it
                        vevent.remove(vevent.rrule)
                        _LOGGER.debug("Removed RRULE from event")

                # Handle recurrence ID for specific instance modifications
                if recurrence_id:
                    if hasattr(vevent, "recurrence-id"):
                        vevent.remove(vevent["recurrence-id"])
                    vevent.add("recurrence-id").value = recurrence_id
                    _LOGGER.debug("Added recurrence-id: %s", recurrence_id)

                # Update the CalDAV event data and save
                caldav_event.data = cal.serialize()
                return caldav_event.save()

            await self.hass.async_add_executor_job(update_event)
            _LOGGER.info("Successfully updated event with UID: %s", uid)
            await self.coordinator.async_refresh()
            
        except Exception as err:
            _LOGGER.error("Error updating calendar event: %s", err, exc_info=True)
            raise HomeAssistantError(f"Error updating calendar event: {err}") from err

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update event data."""
        self._event = self.coordinator.data
        if self._supports_offset:
            self._attr_extra_state_attributes = {
                "offset_reached": is_offset_reached(
                    self._event.start_datetime_local,
                    self.coordinator.offset,  # type: ignore[arg-type]
                )
                if self._event
                else False
            }
        super()._handle_coordinator_update()

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass update state from existing coordinator data."""
        await super().async_added_to_hass()
        self._handle_coordinator_update()


from homeassistant.components.calendar import CalendarEntity, CalendarEntityFeature
from homeassistant.config_entries import ConfigEntry

class CalDavCalendarManagement(CalendarEntity):
    """Calendar management entity."""

    _attr_has_entity_name = True
    _attr_name = "Calendar Management"
    _attr_icon = "mdi:calendar-multiple"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        """Initialize the calendar management."""
        super().__init__()
        self.coordinator = coordinator
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_management"
        self._calendars = []
        self._update_calendars()

    async def _update_calendars(self) -> None:
        """Update list of available calendars."""
        self._calendars = await self.coordinator.client.list_calendars()

    async def create_calendar(self, name: str) -> None:
        """Create a new calendar."""
        try:
            await self.coordinator.client.create_calendar(name)
            await self._update_calendars()
            await self.coordinator.async_refresh()
        except Exception as err:
            raise HomeAssistantError(f"Failed to create calendar: {err}")

    async def delete_calendar(self, calendar_id: str) -> None:
        """Delete a calendar."""
        try:
            await self.coordinator.client.delete_calendar(calendar_id)
            await self._update_calendars()
            await self.coordinator.async_refresh()
        except Exception as err:
            raise HomeAssistantError(f"Failed to delete calendar: {err}")

    @property
    def extra_state_attributes(self):
        """Return the list of available calendars."""
        return {
            "calendars": [
                {"name": cal.name, "id": cal.id} 
                for cal in self._calendars
            ]
        }
