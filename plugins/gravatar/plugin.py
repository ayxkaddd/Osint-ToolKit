"""Gravatar: profiles are found by the MD5 hash of the email address.

An async generator: each ``yield`` shows a card straight away - the profile
first, then one card per account the person verified on Gravatar.
"""
import hashlib

from plugins.sdk import Item, PluginError


async def run(value, type, ctx):
    email_hash = hashlib.md5(value.strip().lower().encode()).hexdigest()
    headers = {"Authorization": f"Bearer {ctx.settings.GRAVATAR_API_KEY}"} if ctx.settings.GRAVATAR_API_KEY else {}
    r = await ctx.http.get(f"https://api.gravatar.com/v3/profiles/{email_hash}", headers=headers)
    if r.status_code == 404:
        return                                  # no profile: "Nothing found"
    if r.status_code == 429:
        raise PluginError("Gravatar rate limit reached - try later or add an API key in Settings")
    r.raise_for_status()
    p = r.json()

    yield Item(
        title=p.get("display_name") or value,
        subtitle=p.get("job_title") or "Gravatar profile",
        url=p.get("profile_url", ""),
        image=p.get("avatar_url", ""),
        fields={
            "Location": p.get("location"),
            "About": p.get("description"),
            "Company": p.get("company"),
            "Pronouns": p.get("pronouns"),
            "Verified accounts": len(p.get("verified_accounts") or []),
        },
        entities={"url": p.get("profile_url")},
    )

    for account in p.get("verified_accounts") or []:
        if account.get("is_hidden"):
            continue
        yield Item(
            title=account.get("service_label") or account.get("service_type", "Account"),
            subtitle="verified on Gravatar",
            url=account.get("url", ""),
            icon=account.get("service_icon", ""),
            category="Verified accounts",
            entities={"url": account.get("url")},
        )
