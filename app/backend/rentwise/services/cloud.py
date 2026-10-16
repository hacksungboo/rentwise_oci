"""실행 위치 증거: OCI 인스턴스 메타데이터 서비스(IMDS v2).

169.254.169.254 는 OCI 인스턴스 안에서만 응답하므로, 화면에 보이는 리전·인스턴스 값은 서버가 직접 읽은 것이다.
OCI 밖(로컬·CI)에서는 provider=local 로 돌려준다. 결과는 5분 캐시.
"""
from __future__ import annotations

import json
import time
import urllib.request
from typing import Any

IMDS = "http://169.254.169.254/opc/v2"
_cache: dict[str, Any] = {"at": 0.0, "value": None}
_started = time.time()


def _get(path: str) -> Any:
    req = urllib.request.Request(f"{IMDS}{path}", headers={"Authorization": "Bearer Oracle"})
    # 프록시 환경변수를 무시하고 링크로컬 주소로 직접 접속
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=1.5) as r:
        return json.loads(r.read())


def cloud_info() -> dict[str, Any]:
    if _cache["value"] is not None and time.time() - _cache["at"] < 300:
        return {**_cache["value"], "uptime_s": int(time.time() - _started)}
    try:
        inst = _get("/instance/")
        try:
            vnics = _get("/vnics/")
        except Exception:  # noqa: BLE001
            vnics = []
        shape_cfg = inst.get("shapeConfig") or {}
        value = {
            "provider": "oci",
            "region": inst.get("canonicalRegionName") or inst.get("region"),
            "availability_domain": inst.get("availabilityDomain"),
            "fault_domain": inst.get("faultDomain"),
            "display_name": inst.get("displayName"),
            "instance_id": inst.get("id"),
            "shape": inst.get("shape"),
            "ocpus": shape_cfg.get("ocpus"),
            "memory_gb": shape_cfg.get("memoryInGBs"),
            "private_ip": (vnics[0] or {}).get("privateIp") if vnics else None,
            "source": "OCI Instance Metadata Service v2 (169.254.169.254)",
        }
    except Exception:  # noqa: BLE001
        value = {"provider": "local", "region": None, "display_name": None,
                 "source": "OCI 메타데이터에 접근할 수 없음 (OCI 밖에서 실행 중)"}
    _cache.update(at=time.time(), value=value)
    return {**value, "uptime_s": int(time.time() - _started)}
