"""IP address intelligence: geolocation/ASN (ipinfo), reverse DNS, abuse
reports (AbuseIPDB) and exposed services (Shodan) when keys are configured."""
import asyncio
import ipaddress
import socket
from typing import Any, Dict, Optional

import httpx

from utils.config import get_setting


class IPLookupError(ValueError):
    pass


class IPService:
    async def lookup_ip(self, ip: str) -> Dict[str, Any]:
        ip = (ip or "").strip()
        try:
            address = ipaddress.ip_address(ip)
        except ValueError as e:
            raise IPLookupError("Not a valid IPv4/IPv6 address") from e

        ip_type = {
            "version": address.version,
            "is_private": address.is_private,
            "is_global": address.is_global,
            "is_loopback": address.is_loopback,
            "is_multicast": address.is_multicast,
        }
        result: Dict[str, Any] = {"ip": str(address), "ip_type": ip_type, "warnings": []}
        if not address.is_global:
            result["warnings"].append("This is not a public address - external sources have nothing on it")
            return result

        async with httpx.AsyncClient(timeout=12) as client:
            basic, abuse, shodan, rdns = await asyncio.gather(
                self._ipinfo(client, str(address)),
                self._abuseipdb(client, str(address)),
                self._shodan(client, str(address)),
                self._reverse_dns(str(address)),
            )
        result.update(basic_info=basic, abuse_info=abuse, shodan_info=shodan, reverse_dns=rdns)
        for name, data in (("ipinfo", basic), ("AbuseIPDB", abuse), ("Shodan", shodan)):
            if isinstance(data, dict) and data.get("error"):
                result["warnings"].append(f"{name}: {data['error']}")
        return result

    async def _ipinfo(self, client: httpx.AsyncClient, ip: str) -> Dict[str, Any]:
        params = {}
        token = get_setting("IPINFO_API_TOKEN")
        if token:
            params["token"] = token
        try:
            response = await client.get(f"https://ipinfo.io/{ip}/json", params=params)
            if response.status_code == 429:
                return {"error": "rate limited - set IPINFO_API_TOKEN for more lookups"}
            response.raise_for_status()
            data = response.json()
            data.pop("readme", None)
            return data
        except (httpx.HTTPError, ValueError) as e:
            return {"error": str(e) or type(e).__name__}

    async def _abuseipdb(self, client: httpx.AsyncClient, ip: str) -> Optional[Dict[str, Any]]:
        key = get_setting("ABUSEIPDB_API_KEY")
        if not key:
            return None
        try:
            response = await client.get(
                "https://api.abuseipdb.com/api/v2/check",
                headers={"Key": key, "Accept": "application/json"},
                params={"ipAddress": ip, "maxAgeInDays": 365, "verbose": "true"},
            )
            response.raise_for_status()
            data = response.json().get("data", {})
            data["reports"] = (data.get("reports") or [])[:20]
            return data
        except (httpx.HTTPError, ValueError) as e:
            return {"error": str(e) or type(e).__name__}

    async def _shodan(self, client: httpx.AsyncClient, ip: str) -> Optional[Dict[str, Any]]:
        key = get_setting("SHODAN_API_KEY")
        if not key:
            return None
        try:
            response = await client.get(f"https://api.shodan.io/shodan/host/{ip}", params={"key": key, "minify": "true"})
            if response.status_code == 404:
                return {"ports": [], "note": "Shodan has no data for this address"}
            response.raise_for_status()
            data = response.json()
            return {k: data.get(k) for k in ("ports", "hostnames", "domains", "os", "org", "isp", "asn", "tags",
                                              "vulns", "last_update", "country_name", "city")}
        except (httpx.HTTPError, ValueError) as e:
            return {"error": str(e) or type(e).__name__}

    @staticmethod
    async def _reverse_dns(ip: str) -> Optional[str]:
        try:
            host, _, _ = await asyncio.wait_for(asyncio.to_thread(socket.gethostbyaddr, ip), timeout=5)
            return host
        except (OSError, asyncio.TimeoutError):
            return None
