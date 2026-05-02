from enum import Enum


class ActionEnum(str, Enum):
    """Enumerates the possible frontend actions the agent can trigger.

    Each action corresponds to a specific UI change or event that the frontend can handle.
    """
    GOTO = "goto"
    ZOOM_TO = "zoom_to"
    SET_SCOPE = "set_scope"
    ADD_CARD_IN_CHAT = "add_card_in_chat"
    ADD_COMPONENT = "add_component"
    NAVIGATE = "navigate"