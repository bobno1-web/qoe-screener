"""OpenDART HTTP 배관 (dartlens-financial-anomaly 패턴 재사용, 판단 로직 없음).

재사용한 것(외부 리포 src/dart_client.py의 배관 설계):
  - 캐시 우선 content-addressed 요청: request_hash = hash(endpoint + API키 제외 정렬 params).
    같은 요청은 스냅샷에서 재현되고 API를 다시 부르지 않는다.
  - 원본 응답 스냅샷 저장 + manifest.jsonl 추적 로그 (출처 추적).
  - 재시도/백오프. 인증(010/011)·점검(800) 상태코드에서 하드스톱(조용한 폴백 금지).
  - corpCode 마스터(ZIP of CORPCODE.xml) 다운로드.

바꾼 것: requests -> urllib (표준 라이브러리만; 새 리포에 서드파티 의존성 추가 안 함).
가져오지 않은 것: 15개 재무비율, peer 스캔, 이상치 판정 — 전부 판단 로직.

API 키는 스냅샷·manifest·로그·request_hash 어디에도 기록하지 않는다.
"""
from __future__ import annotations

import hashlib
import io
import json
import time
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

OPENDART_BASE = "https://opendart.fss.or.kr/api/"


class DartError(RuntimeError):
    """재시도 후에도 실패한 일시적/기술적 오류."""


class StopConditionError(RuntimeError):
    """루프가 반드시 멈춰야 하는 조건(인증 오류, 점검, 폴백 없음)."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def request_hash(endpoint: str, params: dict) -> str:
    """API 키를 제외한 정렬 params로 요청을 지문화. 재현 가능한 캐시 키."""
    safe = {k: v for k, v in params.items() if k != "crtfc_key"}
    blob = endpoint + "?" + "&".join(f"{k}={safe[k]}" for k in sorted(safe))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


class DartClient:
    def __init__(self, api_key, raw_dir, cache_dir, project_root,
                 timeout=20, delay=0.0, max_retries=3):
        self._api_key = api_key
        self.raw_dir = Path(raw_dir)
        self.cache_dir = Path(cache_dir)
        self.project_root = Path(project_root)
        self.timeout = timeout
        self.delay = delay
        self.max_retries = max_retries
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.cache_dir / "manifest.jsonl"

    def _snap_path(self, endpoint_name, h, ext):
        d = self.raw_dir / endpoint_name
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{h}.{ext}"

    def _rel(self, path):
        try:
            return str(Path(path).relative_to(self.project_root)).replace("\\", "/")
        except ValueError:
            return str(path)

    def _record(self, rec):
        with open(self.manifest_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def _http_get(self, endpoint, params) -> bytes:
        url = OPENDART_BASE + endpoint + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": "qoe-normalizer/0.1"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
            return resp.read()

    def get_json(self, endpoint, params, endpoint_name) -> dict:
        """{'data','request_hash','raw_path','from_cache','status'} 반환. 캐시 우선."""
        h = request_hash(endpoint, params)
        snap = self._snap_path(endpoint_name, h, "json")
        safe_params = {k: v for k, v in params.items() if k != "crtfc_key"}

        if snap.exists():
            data = json.loads(snap.read_text(encoding="utf-8"))
            self._record(dict(endpoint=endpoint_name, request_hash=h, params=safe_params,
                              status=data.get("status"), message=data.get("message"),
                              retrieved_at=data.get("_retrieved_at"),
                              raw_path=self._rel(snap), from_cache=True))
            return dict(data=data, request_hash=h, raw_path=self._rel(snap),
                        from_cache=True, status=data.get("status"))

        last_exc = None
        for attempt in range(self.max_retries):
            try:
                if self.delay:
                    time.sleep(self.delay)
                body = self._http_get(endpoint, {**params, "crtfc_key": self._api_key})
                data = json.loads(body.decode("utf-8"))
            except Exception as e:  # 네트워크/디코드
                last_exc = e
                time.sleep(1.5 * (attempt + 1))
                continue

            status = data.get("status")
            if status == "020":  # rate limited -> 백오프 후 재시도
                time.sleep(2.0 * (attempt + 1))
                last_exc = DartError("rate limited (020)")
                continue
            if status in ("010", "011"):
                raise StopConditionError(
                    f"OpenDART 인증 오류(status {status}): API 키를 확인하세요. (STOP)")
            if status == "800":
                raise StopConditionError(
                    "OpenDART 서비스 점검 중(status 800). 나중에 다시 시도하세요. (STOP)")

            data["_retrieved_at"] = _now_iso()
            snap.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            self._record(dict(endpoint=endpoint_name, request_hash=h, params=safe_params,
                              status=status, message=data.get("message"),
                              retrieved_at=data["_retrieved_at"],
                              raw_path=self._rel(snap), from_cache=False))
            return dict(data=data, request_hash=h, raw_path=self._rel(snap),
                        from_cache=False, status=status)

        raise DartError(f"요청 실패({endpoint_name}, {safe_params}): {last_exc}")

    def get_corpcode_xml(self) -> str:
        """corpCode 마스터(ZIP of CORPCODE.xml) 다운로드+캐시."""
        h = request_hash("corpCode.xml", {})
        snap = self._snap_path("corpCode", h, "xml")
        if snap.exists():
            self._record(dict(endpoint="corpCode", request_hash=h, params={},
                              status="000", retrieved_at=None,
                              raw_path=self._rel(snap), from_cache=True))
            return snap.read_text(encoding="utf-8")

        content = self._http_get("corpCode.xml", {"crtfc_key": self._api_key})
        try:
            zf = zipfile.ZipFile(io.BytesIO(content))
            xml = zf.read(zf.namelist()[0]).decode("utf-8")
        except zipfile.BadZipFile:
            raise StopConditionError(
                f"corpCode 조회 실패(키/네트워크 확인): {content[:200]!r} (STOP)")
        snap.write_text(xml, encoding="utf-8")
        self._record(dict(endpoint="corpCode", request_hash=h, params={},
                          status="000", retrieved_at=_now_iso(),
                          raw_path=self._rel(snap), from_cache=False))
        return xml

    def get_document_zip(self, rcept_no: str):
        """document.xml: 원문 문서 ZIP(bytes)을 캐시 우선으로 받는다.

        반환: (content_bytes, raw_path, from_cache). ZIP('PK')이 아니면 하드스톱
        (인증 오류/파라미터 문제로 에러 메시지가 오는 경우).
        """
        h = request_hash("document.xml", {"rcept_no": rcept_no})
        snap = self._snap_path("document", h, "zip")
        if snap.exists():
            self._record(dict(endpoint="document", request_hash=h,
                              params={"rcept_no": rcept_no}, status="000",
                              retrieved_at=None, raw_path=self._rel(snap), from_cache=True))
            return snap.read_bytes(), self._rel(snap), True

        content = self._http_get("document.xml",
                                 {"crtfc_key": self._api_key, "rcept_no": rcept_no})
        if content[:2] != b"PK":
            raise StopConditionError(
                f"document.xml 응답이 ZIP 아님(인증/파라미터 확인): {content[:200]!r} (STOP)")
        snap.write_bytes(content)
        self._record(dict(endpoint="document", request_hash=h,
                          params={"rcept_no": rcept_no}, status="000",
                          retrieved_at=_now_iso(), raw_path=self._rel(snap), from_cache=False))
        return content, self._rel(snap), False
