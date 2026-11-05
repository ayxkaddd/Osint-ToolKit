"""Analytics / ads IDs on web pages (DNS recon and the NS fingerprint): extracted, grouped by ID."""
import asyncio
import json

from services.fingerprint_service import ACCOUNT_TRACKERS, TRACKERS, normalize, trackers_from_extracts

UA, GTM, EMAIL = (TRACKERS[k][1] for k in ("google_analytics_ua", "google_tag_manager", "email"))
EXTRACTS = {UA: ["UA-1234567-1", "UA-1234567-2"], GTM: ["GTM-AB12CD"], EMAIL: ["owner@shop.test"]}


def test_ids_come_from_httpx_extracts():
    assert trackers_from_extracts(EXTRACTS) == {"google_analytics_ua": ["UA-1234567"], "google_tag_manager": ["GTM-AB12CD"],
                                                "email": ["owner@shop.test"]}
    assert "email" not in trackers_from_extracts(EXTRACTS, ACCOUNT_TRACKERS)
    assert normalize({"input": "shop.test", "extracts": EXTRACTS})["trackers"] == trackers_from_extracts(EXTRACTS)


def test_dns_recon_asks_httpx_for_the_ids_and_groups_them(monkeypatch):
    from services import dnsrecon_service
    from utils.subprocess_runner import CommandResult
    commands = []
    lines = [{"input": "shop.acme.test", "extracts": EXTRACTS},
             {"input": "blog.acme.test", "extracts": {UA: ["UA-1234567-3"]}},
             {"input": "www.acme.test"}]

    async def fake_run(cmd, timeout):
        commands.append(cmd)
        return CommandResult(returncode=0, stdout="\n".join(json.dumps(line) for line in lines), stderr="")
    monkeypatch.setattr(dnsrecon_service, "run_command", fake_run)

    service = dnsrecon_service.DNSReconService()
    names = ["shop.acme.test", "blog.acme.test", "www.acme.test"]
    probes = asyncio.run(service.run_httpx_toolkit(names, []))
    assert commands[0].count("-er") == len(ACCOUNT_TRACKERS) and EMAIL not in commands[0]

    rows = service._subdomain_rows(names, {n: [] for n in names}, {}, probes, {})
    assert rows[0]["trackers"] == {"google_analytics_ua": ["UA-1234567"], "google_tag_manager": ["GTM-AB12CD"]}
    assert rows[2]["trackers"] == {}
    assert service._tracking_ids(rows) == [
        {"kind": "google_analytics_ua", "label": "Google Analytics (UA)", "id": "UA-1234567",
         "names": ["shop.acme.test", "blog.acme.test"]},
        {"kind": "google_tag_manager", "label": "Google Tag Manager", "id": "GTM-AB12CD", "names": ["shop.acme.test"]},
    ]
