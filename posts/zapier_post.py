"""
Zapier webhook helper — posts image_url + caption to the Zapier webhook
which is wired to Instagram "Publish Photo(s)".
"""

import os
import requests


def post_to_instagram(image_url: str, caption: str) -> int:
    """
    POST {image_url, caption} to the Zapier webhook.
    Returns the HTTP status code (200 = success).
    """
    webhook_url = os.environ["ZAPIER_WEBHOOK_URL"]
    r = requests.post(
        webhook_url,
        json={"image_url": image_url, "caption": caption},
        timeout=30,
    )
    return r.status_code
