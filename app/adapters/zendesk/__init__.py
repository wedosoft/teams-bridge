"""Zendesk 어댑터"""
from app.adapters.zendesk.client import ZendeskClient
from app.adapters.zendesk.webhook import ZendeskWebhookHandler

__all__ = ["ZendeskClient", "ZendeskWebhookHandler"]
