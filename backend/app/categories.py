"""Kinds of business AgentReady supports: any local business, and any website.

Each category says which read-only tools a customer's AI assistant will expect, and which
actions (flows) the owner will probably need to record. Anything not listed fits "other"
or "online", and the owner can always describe the business in their own words."""

from typing import Any

CATEGORIES: dict[str, dict[str, Any]] = {
    "restaurant": {"label": "Restaurant", "tools": ["get_menu"], "flows": ["book_table"]},
    "cafe": {"label": "Café or bakery", "tools": ["get_menu"], "flows": []},
    "bar": {"label": "Bar or club", "tools": ["get_drinks_menu"], "flows": ["reserve_table"]},
    "hotel": {"label": "Hotel or B&B", "tools": ["get_room_types", "get_prices", "get_check_in_times"], "flows": ["book_room"]},
    "hostel": {"label": "Hostel or holiday rental", "tools": ["get_room_types", "get_prices", "get_check_in_times"], "flows": ["book_stay"]},
    "shop": {"label": "Shop or retail", "tools": ["get_products", "get_prices"], "flows": ["place_order"]},
    "beauty": {"label": "Hair, beauty or spa", "tools": ["get_services_and_prices"], "flows": ["book_appointment"]},
    "health": {"label": "Doctor, dentist or therapist", "tools": ["get_services"], "flows": ["book_appointment"]},
    "fitness": {"label": "Gym, studio or sports", "tools": ["get_classes_and_schedule", "get_prices"], "flows": ["book_class"]},
    "services": {"label": "Home or local services", "tools": ["get_services_and_prices", "get_service_area"], "flows": ["request_quote"]},
    "professional": {"label": "Lawyer, accountant or agency", "tools": ["get_services"], "flows": ["book_consultation"]},
    "education": {"label": "School, courses or tutoring", "tools": ["get_courses", "get_prices"], "flows": ["enroll"]},
    "activities": {"label": "Tours, activities or attractions", "tools": ["get_activities", "get_prices"], "flows": ["book_activity"]},
    "events": {"label": "Events, venue or tickets", "tools": ["get_upcoming_events", "get_prices"], "flows": ["buy_tickets"]},
    "rental": {"label": "Rentals (cars, bikes, equipment)", "tools": ["get_items_for_rent", "get_prices"], "flows": ["make_reservation"]},
    "online": {"label": "Online business or any website", "tools": ["get_overview", "get_products_or_services", "get_faq"], "flows": ["send_inquiry"]},
    "other": {"label": "Something else", "tools": ["get_overview"], "flows": []},
}


def label(category: str, own_words: str = "") -> str:
    """How to name the business in prompts and messages: the owner's words win."""
    return (own_words or "").strip() or CATEGORIES.get(category, CATEGORIES["other"])["label"].lower()


def template(category: str, online_only: bool, has_hours: bool) -> dict[str, list[str]]:
    """The tools and flows a customer's assistant will expect from this business."""
    base = CATEGORIES.get(category, CATEGORIES["other"])
    tools = list(base["tools"])
    if has_hours or not online_only:
        tools.append("get_opening_hours")
    tools.append("get_contact" if online_only else "get_location_and_contact")
    return {"tools": tools, "flows": list(base["flows"])}
