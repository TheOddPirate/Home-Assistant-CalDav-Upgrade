# Home Assistant CalDAV Integration with Event Management

This is an enhanced version of the default Home Assistant CalDAV integration, adding full support for calendar event management directly from the Home Assistant UI.

## Features

- All original CalDAV integration features
- Create new calendar events
- Delete existing events
- Edit event details including:
  - Summary/Title
  - Start/End times
  - Description
  - Location
  - Recurrence rules (recurring events)

## Installation

### HACS (Recommended)|
1. Add this repository to HACS as a custom repository
2. Install the integration through HACS
3. Restart Home Assistant

### Manual Installation
1. Copy the `custom_components/caldav` directory to your Home Assistant's custom_components directory
2. Restart Home Assistant

## Configuration

Configure the integration through the Home Assistant UI:
1. Go to Settings -> Devices & Services
2. Click "Add Integration"
3. Search for "UpgradedCalDav"
4. Enter your CalDAV server details:
   - Server URL
   - Username
   - Password
   - Optional: Verify SSL certificate

## Usage

After configuration:
- Your CalDAV calendars will appear in Home Assistant's calendar UI
- Create new events using the "+" button
- Edit events by clicking on them and using the edit button
- Delete events using the delete option in the event details view

## Supported CalDAV Servers

This integration has been tested with:
- Baikal
- NextCloud
- Others using the CalDAV standard should work as well

## Requirements

- Home Assistant 2023.x or newer
- A CalDAV-compatible server
- Python packages:
  - caldav==1.3.9
  - icalendar==6.1.0

## Credits

This integration is a fork of the official Home Assistant CalDAV integration, enhanced with event management capabilities. Thanks to:
- The Home Assistant team for the original CalDAV integration
- The CalDAV library maintainers

### Development Note

This integration was developed with the assistance of GitHub Copilot, which helped:
- Implement full CRUD operations for calendar events
- Debug and resolve timezone handling issues
- Add proper recurring event support
- Ensure compatibility with various CalDAV servers

## Contributing

Feel free to submit issues and pull requests to help improve this integration.

## License

This project is licensed under the Apache License 2.0 - see the LICENSE file for home assistant for details