from enum import Enum


class ActionEnum(str, Enum):
    """Enumerates the possible frontend actions the agent can trigger.

    Each action corresponds to a specific UI change or event that the frontend can handle.
    """

    OPEN_DASHBOARD = "open_dashboard"
    TOGGLE_LAYER = "toggle_layer"
    FOCUS_DISTRICT = "focus_district"
    SET_SCOPE = "set_scope"
    REQUEST_MAP_INFO = "request_map_info"
    SHOW_COMPONENT = "show_component"
    ADD_COMPONENT = "add_component"
    NAVIGATE = "navigate"