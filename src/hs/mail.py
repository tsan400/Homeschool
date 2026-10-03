"""Outgoing email (sign-in links). Uses Resend when RESEND_API_KEY is set; otherwise prints to the
server log, which is fine for local development."""

import os

import httpx

outbox: list[dict] = []  # what was sent, for tests and local development


def send(to: str, subject: str, text: str):
    msg = {"from": os.environ.get("HS_MAIL_FROM", "Homeschool <onboarding@resend.dev>"),
           "to": [to], "subject": subject, "text": text}
    outbox.append(msg)
    key = os.environ.get("RESEND_API_KEY")
    if not key:
        print(f"[mail] to {to}: {subject}\n{text}", flush=True)
        return
    r = httpx.post("https://api.resend.com/emails", json=msg, timeout=15,
                   headers={"Authorization": f"Bearer {key}"})
    r.raise_for_status()
