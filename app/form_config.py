"""Single source of truth for the guided forms.

The backend uses this to decide which answers to keep. The frontend fetches it
from GET /api/forms and builds each form from it, so the two never drift apart.
Nothing here is enforced as required: testers are never blocked by a field.
"""

FORMS = {
    "bug": {
        "label": "Bug",
        "title": "Report a bug",
        "intro": "Tell us what went wrong. Rough notes are fine.",
        "title_field": "actual",
        "fields": [
            {
                "key": "expected",
                "label": "What did you expect to happen?",
                "type": "textarea",
                "placeholder": "For example: the report downloads as a PDF.",
            },
            {
                "key": "actual",
                "label": "What actually happened?",
                "type": "textarea",
                "placeholder": "For example: the spinner kept going and nothing downloaded.",
            },
            {
                "key": "steps",
                "label": "Steps to reproduce",
                "type": "textarea",
                "placeholder": "Which buttons did you click, in order?",
            },
            {
                "key": "page",
                "label": "Page or screen",
                "type": "text",
                "optional": True,
                "placeholder": "For example: Export page",
            },
            {
                "key": "browser",
                "label": "Browser or device",
                "type": "text",
                "optional": True,
                "placeholder": "For example: Chrome on a work laptop",
            },
        ],
    },
    "awkward": {
        "label": "Awkward",
        "title": "Tell us what felt awkward",
        "intro": "It worked, but something felt off. That still matters.",
        "title_field": "felt_wrong",
        "fields": [
            {
                "key": "trying",
                "label": "What were you trying to do?",
                "type": "textarea",
                "placeholder": "For example: find last month's invoices.",
            },
            {
                "key": "felt_wrong",
                "label": "What felt wrong or confusing?",
                "type": "textarea",
                "placeholder": "For example: I couldn't tell which button saved my work.",
            },
            {
                "key": "more_natural",
                "label": "What would have felt more natural?",
                "type": "textarea",
                "optional": True,
                "placeholder": "Only if you have an idea.",
            },
        ],
    },
    "suggestion": {
        "label": "Suggestion",
        "title": "Share a suggestion",
        "intro": "Good ideas are welcome, even when nothing is broken.",
        "title_field": "idea",
        "fields": [
            {
                "key": "idea",
                "label": "What's your idea?",
                "type": "textarea",
                "placeholder": "Describe it in your own words.",
            },
            {
                "key": "problem",
                "label": "What problem would it solve?",
                "type": "textarea",
                "optional": True,
                "placeholder": "Who would it help, and how?",
            },
        ],
    },
    "extra": {
        "label": "Extra",
        "title": "Anything else",
        "intro": "A question, a note, or something you think is missing.",
        "title_field": "note",
        "fields": [
            {
                "key": "note",
                "label": "What would you like to tell us?",
                "type": "textarea",
                "placeholder": "Write as much or as little as you like.",
            },
        ],
    },
}
