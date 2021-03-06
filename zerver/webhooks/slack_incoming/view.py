# Webhooks for external integrations.
from typing import Any, Dict, Optional

from django.http import HttpRequest, HttpResponse

from zerver.decorator import api_key_only_webhook_view
from zerver.lib.request import REQ, has_request_variables
from zerver.lib.response import json_success
from zerver.lib.webhooks.common import check_send_webhook_message
from zerver.lib.exceptions import InvalidJSONError
from django.utils.translation import ugettext as _
from zerver.models import UserProfile
import re
import ujson

@api_key_only_webhook_view('SlackIncoming')
@has_request_variables
def api_slack_incoming_webhook(request: HttpRequest, user_profile: UserProfile,
                               user_specified_topic: Optional[str]=REQ("topic", default=None),
                               payload: Optional[Dict[str, Any]] = REQ(
                                   'payload',
                                   converter=ujson.loads,
                                   default=None)) -> HttpResponse:

    # Slack accepts webhook payloads as payload="encoded json" as
    # application/x-www-form-urlencoded, as well as in the body as
    # application/json. We use has_request_variables to try to get
    # the form encoded version, and parse the body out ourselves if
    # # we were given JSON.
    if payload is None:
        try:
            payload = ujson.loads(request.body)
        except ValueError:  # nocoverage
            raise InvalidJSONError(_("Malformed JSON"))

    if user_specified_topic is None and "channel" in payload:
        user_specified_topic = re.sub("^[@#]", "", payload["channel"])

    if user_specified_topic is None:
        user_specified_topic = "(no topic)"

    body = ""

    if "blocks" in payload:
        for block in payload["blocks"]:
            body = add_block(block, body)

    if "attachments" in payload:
        for attachment in payload["attachments"]:
            body = add_attachment(attachment, body)

    if body == "" and "text" in payload:
        body += payload["text"]
        if "icon_emoji" in payload and payload["icon_emoji"] is not None:
            body = "{} {}".format(payload["icon_emoji"], body)

    if body != "":
        body = replace_formatting(replace_links(body).strip())
        check_send_webhook_message(request, user_profile, user_specified_topic, body)
    return json_success()


def add_block(block: Dict[str, Any], body: str) -> str:
    block_type = block.get("type", None)
    if block_type == "section":
        if "text" in block:
            text = block["text"]
            while type(text) == dict:  # handle stuff like block["text"]["text"]
                text = text["text"]
            body += f"\n\n{text}"

        if "accessory" in block:
            accessory = block["accessory"]
            accessory_type = accessory["type"]
            if accessory_type == "image":
                # This should become ![text](url) once proper Markdown images are supported
                body += "\n[{alt_text}]({image_url})".format(**accessory)

    return body

def add_attachment(attachment: Dict[str, Any], body: str) -> str:
    attachment_body = ""
    if "title" in attachment and "title_link" in attachment:
        attachment_body += "[{title}]({title_link})\n".format(**attachment)
    if "text" in attachment:
        attachment_body += attachment["text"]

    return body + attachment_body

def replace_links(text: str) -> str:
    return re.sub(r"<(\w+?:\/\/.*?)\|(.*?)>", r"[\2](\1)", text)

def replace_formatting(text: str) -> str:
    # Slack uses *text* for bold, whereas Zulip interprets that as italics
    text = re.sub(r'([^\w])\*(?!\s+)([^\*^\n]+)(?<!\s)\*([^\w])', r"\1**\2**\3", text)

    # Slack uses _text_ for emphasis, whereas Zulip interprets that as nothing
    text = re.sub(r"([^\w])[_](?!\s+)([^\_\^\n]+)(?<!\s)[_]([^\w])", r"\1**\2**\3", text)
    return text
