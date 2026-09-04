import httpx
import datetime
import logging
from typing import Optional, List, Dict, Set

logger = logging.getLogger(__name__)


class SupabaseDatabase:
    """
    Direct Supabase PostgREST REST API Database Client.
    Uses standard HTTPS REST calls with service_role / anon key.
    """
    def __init__(self, supabase_url: str, supabase_key: str):
        self.url = supabase_url.rstrip("/")
        self.key = supabase_key
        self.headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }
        self.client = httpx.Client(base_url=f"{self.url}/rest/v1", headers=self.headers, timeout=30.0)
        logger.info("Supabase REST API Database initialized for %s", self.url)

    def _req(self, method: str, endpoint: str, **kwargs) -> httpx.Response:
        try:
            res = self.client.request(method, endpoint, **kwargs)
            res.raise_for_status()
            return res
        except Exception as e:
            logger.error("Supabase REST error on %s %s: %s", method, endpoint, e)
            raise

    # -------------------------------------------------------------
    # Users
    # -------------------------------------------------------------
    def get_or_create_user(
        self,
        telegram_id: int,
        username: Optional[str] = None,
        full_name: Optional[str] = None
    ) -> None:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        try:
            # 1. Check if user already exists
            check_res = self.client.get(f"/users?telegram_id=eq.{telegram_id}&select=id&limit=1")
            if check_res.status_code == 200 and check_res.json():
                # User exists, optionally update username & full_name
                patch_payload = {}
                if username:
                    patch_payload["username"] = username
                if full_name:
                    patch_payload["full_name"] = full_name
                if patch_payload:
                    try:
                        self.client.patch(f"/users?telegram_id=eq.{telegram_id}", json=patch_payload)
                    except Exception:
                        pass
                return

            # 2. User does not exist, insert
            new_payload = {"telegram_id": telegram_id, "created_at": now}
            if username:
                new_payload["username"] = username
            if full_name:
                new_payload["full_name"] = full_name

            ins_res = self.client.post("/users", json=new_payload)
            if ins_res.status_code >= 400:
                # If failed due to extra column mismatch, fallback to basic schema
                self.client.post("/users", json={"telegram_id": telegram_id, "created_at": now})
        except Exception as e:
            logger.debug("get_or_create_user notice: %s", e)

    # -------------------------------------------------------------
    # Shipments & Chains
    # -------------------------------------------------------------
    def get_or_create_shipment(
        self,
        tracking_number: str,
        telegram_id: Optional[int] = None,
        label: Optional[str] = None
    ) -> int:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        cleaned_num = tracking_number.strip().upper()

        # 1. Check if number exists in shipment_tracking_numbers
        res = self._req("GET", f"/shipment_tracking_numbers?tracking_number=eq.{cleaned_num}&select=shipment_id&limit=1")
        rows = res.json()

        if rows:
            shipment_id = rows[0]["shipment_id"]
        else:
            # 2. Check if primary in shipments
            s_res = self._req("GET", f"/shipments?primary_tracking_number=eq.{cleaned_num}&select=id&limit=1")
            s_rows = s_res.json()

            if s_rows:
                shipment_id = s_rows[0]["id"]
            else:
                # 3. Insert new shipment
                new_s = self._req("POST", "/shipments", json={
                    "primary_tracking_number": cleaned_num,
                    "created_at": now,
                    "updated_at": now
                }).json()
                shipment_id = new_s[0]["id"]

            # Add original tracking number to chain
            try:
                self._req("POST", "/shipment_tracking_numbers", json={
                    "shipment_id": shipment_id,
                    "tracking_number": cleaned_num,
                    "source": "original",
                    "type": "original",
                    "created_at": now
                }, headers={**self.headers, "Prefer": "resolution=ignore-duplicates"})
            except Exception:
                pass

        # 4. Subscribe user if telegram_id provided
        if telegram_id is not None:
            self.get_or_create_user(telegram_id)
            sub_payload = {
                "shipment_id": shipment_id,
                "telegram_id": telegram_id,
                "label": label,
                "active": 1,
                "created_at": now
            }
            try:
                self._req("POST", "/shipment_subscribers", json=sub_payload, headers={**self.headers, "Prefer": "resolution=merge-duplicates"})
            except Exception:
                self._req("PATCH", f"/shipment_subscribers?shipment_id=eq.{shipment_id}&telegram_id=eq.{telegram_id}", json={"active": 1, "label": label})

            try:
                self._req("POST", "/trackings", json={
                    "telegram_id": telegram_id,
                    "tracking_number": cleaned_num,
                    "label": label,
                    "active": 1,
                    "created_at": now
                }, headers={**self.headers, "Prefer": "resolution=merge-duplicates"})
            except Exception:
                pass

        return shipment_id

    def link_tracking_number(
        self,
        shipment_id: int,
        tracking_number: str,
        source: str = "cainiao",
        num_type: str = "linked",
        discovered_from: Optional[str] = None
    ) -> bool:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        cleaned_num = tracking_number.strip().upper()

        # Check existing
        res = self._req("GET", f"/shipment_tracking_numbers?tracking_number=eq.{cleaned_num}&select=shipment_id")
        rows = res.json()

        if rows:
            other_id = rows[0]["shipment_id"]
            if other_id != shipment_id:
                # Merge
                self._req("PATCH", f"/shipment_tracking_numbers?shipment_id=eq.{other_id}", json={"shipment_id": shipment_id})
                self._req("PATCH", f"/shipment_subscribers?shipment_id=eq.{other_id}", json={"shipment_id": shipment_id})
                self._req("DELETE", f"/shipments?id=eq.{other_id}")
            return False

        try:
            self._req("POST", "/shipment_tracking_numbers", json={
                "shipment_id": shipment_id,
                "tracking_number": cleaned_num,
                "source": source,
                "type": num_type,
                "discovered_from": discovered_from,
                "created_at": now
            }, headers={**self.headers, "Prefer": "resolution=ignore-duplicates"})

            if num_type == "local" or source == "bdpost":
                self._req("PATCH", f"/shipments?id=eq.{shipment_id}", json={"local_tracking_number": cleaned_num, "updated_at": now})

            return True
        except Exception:
            return False

    def get_shipment(self, shipment_id: int) -> Optional[Dict]:
        res = self._req("GET", f"/shipments?id=eq.{shipment_id}&select=*&limit=1")
        rows = res.json()
        if not rows:
            return None
        shipment = rows[0]
        chain_res = self._req("GET", f"/shipment_tracking_numbers?shipment_id=eq.{shipment_id}&select=*&order=id.asc")
        shipment["tracking_chain"] = chain_res.json()
        return shipment

    def get_shipment_by_tracking_number(self, tracking_number: str) -> Optional[Dict]:
        cleaned_num = tracking_number.strip().upper()
        res = self._req("GET", f"/shipment_tracking_numbers?tracking_number=eq.{cleaned_num}&select=shipment_id&limit=1")
        rows = res.json()
        if rows:
            return self.get_shipment(rows[0]["shipment_id"])

        s_res = self._req("GET", f"/shipments?primary_tracking_number=eq.{cleaned_num}&select=id&limit=1")
        s_rows = s_res.json()
        if s_rows:
            return self.get_shipment(s_rows[0]["id"])

        return None

    def get_tracking_chain_numbers(self, shipment_id: int) -> List[str]:
        res = self._req("GET", f"/shipment_tracking_numbers?shipment_id=eq.{shipment_id}&is_active=eq.1&select=tracking_number&order=id.asc")
        return [r["tracking_number"] for r in res.json()]

    def update_shipment_status(
        self,
        shipment_id: int,
        status: Optional[str] = None,
        location: Optional[str] = None,
        cainiao_enabled: Optional[int] = None,
        bdpost_enabled: Optional[int] = None,
        handover_detected: Optional[int] = None,
        handover_event_hash: Optional[str] = None,
        is_delivered: Optional[int] = None,
        local_tracking_number: Optional[str] = None
    ) -> None:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        payload = {"updated_at": now}

        if status is not None:
            payload["current_status"] = status
        if location is not None:
            payload["current_location"] = location
        if cainiao_enabled is not None:
            payload["cainiao_enabled"] = cainiao_enabled
        if bdpost_enabled is not None:
            payload["bdpost_enabled"] = bdpost_enabled
        if handover_detected is not None:
            payload["handover_detected"] = handover_detected
            if handover_detected and handover_event_hash:
                payload["handover_at"] = now
                payload["handover_event_hash"] = handover_event_hash
        if is_delivered is not None:
            payload["is_delivered"] = is_delivered
        if local_tracking_number is not None:
            payload["local_tracking_number"] = local_tracking_number

        self._req("PATCH", f"/shipments?id=eq.{shipment_id}", json=payload)

    def get_shipment_subscribers(self, shipment_id: int) -> List[Dict]:
        res = self._req("GET", f"/shipment_subscribers?shipment_id=eq.{shipment_id}&active=eq.1&select=telegram_id,label")
        return res.json()

    def get_user_active_shipments(self, telegram_id: int) -> List[Dict]:
        sub_res = self._req("GET", f"/shipment_subscribers?telegram_id=eq.{telegram_id}&active=eq.1&select=shipment_id,label")
        sub_rows = sub_res.json()
        if not sub_rows:
            return []

        shipments = []
        for r in sub_rows:
            sid = r["shipment_id"]
            shipment = self.get_shipment(sid)
            if shipment:
                shipment["label"] = r.get("label")
                shipments.append(shipment)
        return shipments

    def get_all_active_shipments(self) -> List[Dict]:
        # Get shipments with active subscribers and not delivered
        s_res = self._req("GET", "/shipments?is_delivered=eq.0&select=*")
        shipments = s_res.json()
        active = []
        for s in shipments:
            subs = self.get_shipment_subscribers(s["id"])
            if subs:
                chain = self._req("GET", f"/shipment_tracking_numbers?shipment_id=eq.{s['id']}&is_active=eq.1&select=*&order=id.asc").json()
                s["tracking_chain"] = chain
                active.append(s)
        return active

    def has_events_for_shipment(self, shipment_id: int) -> bool:
        chain_numbers = self.get_tracking_chain_numbers(shipment_id)
        if not chain_numbers:
            return False
        in_filter = f"({','.join(chain_numbers)})"
        res = self._req("GET", f"/events?tracking_number=in.{in_filter}&select=id&limit=1")
        return len(res.json()) > 0

    def get_stale_unscanned_shipments(self, days: int = 10) -> List[Dict]:
        now = datetime.datetime.now(datetime.timezone.utc)
        active_shipments = self.get_all_active_shipments()
        stale = []
        for s in active_shipments:
            created_at_str = s.get("created_at", "")
            try:
                created_dt = datetime.datetime.fromisoformat(created_at_str)
                if created_dt.tzinfo is None:
                    created_dt = created_dt.replace(tzinfo=datetime.timezone.utc)
                if (now - created_dt).total_seconds() >= days * 86400:
                    if not self.has_events_for_shipment(s["id"]):
                        stale.append(s)
            except Exception as e:
                logger.debug("Error checking age of shipment %s: %s", s.get("primary_tracking_number"), e)
        return stale

    def expire_stale_shipment(self, shipment_id: int) -> int:
        self._req("PATCH", f"/shipments?id=eq.{shipment_id}", json={"cainiao_enabled": 0, "bdpost_enabled": 0})
        res = self._req("PATCH", f"/shipment_subscribers?shipment_id=eq.{shipment_id}", json={"active": 0})
        return len(res.json()) if isinstance(res.json(), list) else 1

    def stop_shipment_tracking(self, telegram_id: int, tracking_number: str) -> bool:
        cleaned_num = tracking_number.strip().upper()
        shipment = self.get_shipment_by_tracking_number(cleaned_num)
        if not shipment:
            return False

        sid = shipment["id"]
        res = self._req("PATCH", f"/shipment_subscribers?shipment_id=eq.{sid}&telegram_id=eq.{telegram_id}&active=eq.1", json={"active": 0})
        return len(res.json()) > 0

    def stop_all_user_shipments(self, telegram_id: int) -> int:
        res = self._req("PATCH", f"/shipment_subscribers?telegram_id=eq.{telegram_id}&active=eq.1", json={"active": 0})
        return len(res.json()) if isinstance(res.json(), list) else 1

    def deactivate_shipment_on_delivery(self, shipment_id: int) -> int:
        self._req("PATCH", f"/shipments?id=eq.{shipment_id}", json={"is_delivered": 1, "cainiao_enabled": 0, "bdpost_enabled": 0})
        res = self._req("PATCH", f"/shipment_subscribers?shipment_id=eq.{shipment_id}", json={"active": 0})
        return len(res.json()) if isinstance(res.json(), list) else 1

    def set_shipment_label(self, telegram_id: int, tracking_number: str, label: Optional[str]) -> bool:
        cleaned_num = tracking_number.strip().upper()
        shipment = self.get_shipment_by_tracking_number(cleaned_num)
        if not shipment:
            return False
        sid = shipment["id"]
        res = self._req("PATCH", f"/shipment_subscribers?shipment_id=eq.{sid}&telegram_id=eq.{telegram_id}", json={"label": label.strip() if label else None})
        return len(res.json()) > 0

    # -------------------------------------------------------------
    # Legacy / Common Compatibility
    # -------------------------------------------------------------
    def add_or_reactivate_tracking(self, telegram_id: int, tracking_number: str, **kwargs) -> None:
        self.get_or_create_shipment(tracking_number, telegram_id=telegram_id)

    def stop_tracking(self, telegram_id: int, tracking_number: str) -> bool:
        return self.stop_shipment_tracking(telegram_id, tracking_number)

    def stop_all_trackings(self, telegram_id: int) -> int:
        return self.stop_all_user_shipments(telegram_id)

    def deactivate_tracking_number(self, tracking_number: str) -> int:
        shipment = self.get_shipment_by_tracking_number(tracking_number)
        if shipment:
            return self.deactivate_shipment_on_delivery(shipment["id"])
        return 0

    def set_parcel_label(self, telegram_id: int, tracking_number: str, label: Optional[str]) -> bool:
        return self.set_shipment_label(telegram_id, tracking_number, label)

    def get_parcel_label(self, telegram_id: int, tracking_number: str) -> Optional[str]:
        shipment = self.get_shipment_by_tracking_number(tracking_number)
        if shipment:
            subs = self.get_shipment_subscribers(shipment["id"])
            for sub in subs:
                if sub["telegram_id"] == telegram_id:
                    return sub["label"]
        return None

    def set_handover_detected(self, tracking_number: str, handover_event_hash: str) -> None:
        shipment = self.get_shipment_by_tracking_number(tracking_number)
        if shipment:
            self.update_shipment_status(
                shipment["id"],
                cainiao_enabled=0,
                bdpost_enabled=1,
                handover_detected=1,
                handover_event_hash=handover_event_hash
            )

    def get_user_active_trackings(self, telegram_id: int) -> List[Dict]:
        shipments = self.get_user_active_shipments(telegram_id)
        result = []
        for s in shipments:
            result.append({
                "tracking_number": s["primary_tracking_number"],
                "label": s.get("label"),
                "cainiao_enabled": s["cainiao_enabled"],
                "bdpost_enabled": s["bdpost_enabled"],
                "handover_detected": s["handover_detected"],
                "local_tracking_number": s.get("local_tracking_number"),
                "tracking_chain": s.get("tracking_chain", []),
                "created_at": s["created_at"],
                "last_checked_at": s["last_checked_at"]
            })
        return result

    def get_subscribers_with_labels_for_tracking(self, tracking_number: str) -> List[Dict]:
        shipment = self.get_shipment_by_tracking_number(tracking_number)
        if shipment:
            return self.get_shipment_subscribers(shipment["id"])
        return []

    def get_all_active_tracking_numbers(self) -> List[str]:
        shipments = self.get_all_active_shipments()
        return [s["primary_tracking_number"] for s in shipments]

    def get_active_trackings_with_providers(self) -> List[Dict]:
        shipments = self.get_all_active_shipments()
        result = []
        for s in shipments:
            result.append({
                "shipment_id": s["id"],
                "tracking_number": s["primary_tracking_number"],
                "local_tracking_number": s.get("local_tracking_number"),
                "tracking_chain": s.get("tracking_chain", []),
                "cainiao_enabled": s["cainiao_enabled"],
                "bdpost_enabled": s["bdpost_enabled"],
                "handover_detected": s["handover_detected"],
                "handover_at": s["handover_at"],
                "handover_event_hash": s["handover_event_hash"]
            })
        return result

    def get_subscribers_for_tracking(self, tracking_number: str) -> List[int]:
        subs = self.get_subscribers_with_labels_for_tracking(tracking_number)
        return [s["telegram_id"] for s in subs]

    def update_last_checked(self, tracking_number: str) -> None:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        try:
            self._req("PATCH", f"/shipments?primary_tracking_number=eq.{tracking_number}", json={"last_checked_at": now, "updated_at": now})
        except Exception:
            pass

    def get_known_event_hashes(self, tracking_number: str) -> Set[str]:
        shipment = self.get_shipment_by_tracking_number(tracking_number)
        all_numbers = [tracking_number]
        if shipment:
            all_numbers.extend([item["tracking_number"] for item in shipment.get("tracking_chain", [])])

        in_filter = f"({','.join(all_numbers)})"
        res = self._req("GET", f"/events?tracking_number=in.{in_filter}&select=event_hash")
        return {r["event_hash"] for r in res.json()}

    def save_events(self, tracking_number: str, events: List[Dict]) -> List[Dict]:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        known_hashes = self.get_known_event_hashes(tracking_number)
        new_events = []

        # Fetch existing events for signature deduplication
        shipment = self.get_shipment_by_tracking_number(tracking_number)
        all_numbers = [tracking_number]
        if shipment:
            all_numbers.extend([item["tracking_number"] for item in shipment.get("tracking_chain", [])])

        in_filter = f"({','.join(all_numbers)})"
        try:
            existing_res = self._req("GET", f"/events?tracking_number=in.{in_filter}&select=event_date,status,description").json()
        except Exception:
            existing_res = []

        existing_signatures = set()
        for r in existing_res:
            d = str(r.get("event_date") or "").strip()[:16]
            st = str(r.get("status") or "").strip().lower()
            desc = str(r.get("description") or "").strip().lower()
            if d and st:
                existing_signatures.add((d, st))
            if d and desc:
                existing_signatures.add((d, desc))

        for event in events:
            event_hash = event["event_hash"]
            evt_date = str(event.get("event_date", "")).strip()[:16]
            evt_status = str(event.get("status", "")).strip().lower()
            evt_desc = str(event.get("description", "")).strip().lower()

            if event_hash in known_hashes:
                continue

            if evt_date and ((evt_date, evt_status) in existing_signatures or (evt_date, evt_desc) in existing_signatures):
                continue

            payload = {
                "tracking_number": event.get("tracking_number", tracking_number),
                "event_date": event.get("event_date", ""),
                "origin_country": event.get("origin_country", ""),
                "destination_country": event.get("destination_country", ""),
                "location": event.get("location", ""),
                "status": event.get("status", ""),
                "description": event.get("description", ""),
                "source": event.get("source", "bdpost"),
                "action_code": event.get("action_code", ""),
                "timezone": event.get("timezone", ""),
                "event_hash": event_hash,
                "created_at": now
            }
            try:
                self._req("POST", "/events", json=payload, headers={**self.headers, "Prefer": "resolution=ignore-duplicates"})
                new_events.append(event)
                known_hashes.add(event_hash)
                if evt_date:
                    existing_signatures.add((evt_date, evt_status))
                    existing_signatures.add((evt_date, evt_desc))
            except Exception as e:
                logger.debug("Event insert notice: %s", e)

        return new_events

    def get_latest_event_for_tracking(self, tracking_number: str) -> Optional[Dict]:
        shipment = self.get_shipment_by_tracking_number(tracking_number)
        all_numbers = [tracking_number]
        if shipment:
            all_numbers.extend([item["tracking_number"] for item in shipment.get("tracking_chain", [])])

        in_filter = f"({','.join(all_numbers)})"
        res = self._req("GET", f"/events?tracking_number=in.{in_filter}&select=*&order=id.desc&limit=1")
        rows = res.json()
        if rows:
            return rows[0]
        return None

    # -------------------------------------------------------------
    # Admin Control & Oversight Methods
    # -------------------------------------------------------------
    def get_system_stats(self) -> Dict:
        try:
            users_res = self._req("GET", "/users?select=count", headers={**self.headers, "Prefer": "count=exact"}).headers.get("content-range", "")
            total_users = int(users_res.split("/")[-1]) if "/" in users_res else len(self._req("GET", "/users?select=telegram_id").json())
        except Exception:
            total_users = 0

        try:
            shipments_res = self._req("GET", "/shipments?select=count", headers={**self.headers, "Prefer": "count=exact"}).headers.get("content-range", "")
            total_shipments = int(shipments_res.split("/")[-1]) if "/" in shipments_res else len(self._req("GET", "/shipments?select=id").json())
        except Exception:
            total_shipments = 0

        try:
            active_shipments = len(self.get_all_active_shipments())
        except Exception:
            active_shipments = 0

        try:
            deliv_res = self._req("GET", "/shipments?is_delivered=eq.1&select=count", headers={**self.headers, "Prefer": "count=exact"}).headers.get("content-range", "")
            delivered = int(deliv_res.split("/")[-1]) if "/" in deliv_res else len(self._req("GET", "/shipments?is_delivered=eq.1&select=id").json())
        except Exception:
            delivered = 0

        try:
            ho_res = self._req("GET", "/shipments?handover_detected=eq.1&select=count", headers={**self.headers, "Prefer": "count=exact"}).headers.get("content-range", "")
            handover_count = int(ho_res.split("/")[-1]) if "/" in ho_res else len(self._req("GET", "/shipments?handover_detected=eq.1&select=id").json())
        except Exception:
            handover_count = 0

        try:
            ban_res = self.client.get("/users?is_banned=eq.1&select=count", headers={**self.headers, "Prefer": "count=exact"})
            if ban_res.status_code == 200:
                header_range = ban_res.headers.get("content-range", "")
                banned_users = int(header_range.split("/")[-1]) if "/" in header_range else 0
            else:
                banned_users = 0
        except Exception:
            banned_users = 0

        return {
            "total_users": total_users,
            "total_shipments": total_shipments,
            "active_shipments": active_shipments,
            "delivered_shipments": delivered,
            "handover_shipments": handover_count,
            "banned_users": banned_users
        }

    def get_all_users_admin(self, limit: int = 50, offset: int = 0) -> List[Dict]:
        try:
            users = self._req("GET", f"/users?select=*&order=id.desc&limit={limit}&offset={offset}").json()
            for u in users:
                uid = u["telegram_id"]
                sub_res = self._req("GET", f"/shipment_subscribers?telegram_id=eq.{uid}&select=active").json()
                u["total_parcels"] = len(sub_res)
                u["active_parcels"] = len([s for s in sub_res if s.get("active") == 1])
            return users
        except Exception as e:
            logger.error("get_all_users_admin error: %s", e)
            return []

    def get_user_admin_profile(self, identifier: str) -> Optional[Dict]:
        cleaned = identifier.strip().lstrip("@")
        try:
            if cleaned.isdigit():
                res = self._req("GET", f"/users?telegram_id=eq.{int(cleaned)}&limit=1").json()
            else:
                res = self._req("GET", f"/users?username=ilike.{cleaned}&limit=1").json()
            if not res:
                return None
            user_data = res[0]
            user_data["parcels"] = self.get_user_parcels_admin(user_data["telegram_id"])
            return user_data
        except Exception as e:
            logger.error("get_user_admin_profile error: %s", e)
            return None

    def get_user_parcels_admin(self, telegram_id: int) -> List[Dict]:
        try:
            subs = self._req("GET", f"/shipment_subscribers?telegram_id=eq.{telegram_id}&order=active.desc").json()
            parcels = []
            for sub in subs:
                sid = sub["shipment_id"]
                s_res = self._req("GET", f"/shipments?id=eq.{sid}&limit=1").json()
                if s_res:
                    s = s_res[0]
                    s["label"] = sub.get("label")
                    s["is_subscribed"] = sub.get("active")
                    s["subscribed_at"] = sub.get("created_at")
                    s["latest_event"] = self.get_latest_event_for_tracking(s["primary_tracking_number"])
                    chain = self._req("GET", f"/shipment_tracking_numbers?shipment_id=eq.{sid}&select=*&order=id.asc").json()
                    s["tracking_chain"] = chain
                    parcels.append(s)
            return parcels
        except Exception as e:
            logger.error("get_user_parcels_admin error: %s", e)
            return []

    def get_all_shipments_admin(self, limit: int = 50, offset: int = 0) -> List[Dict]:
        try:
            shipments = self._req("GET", f"/shipments?select=*&order=updated_at.desc&limit={limit}&offset={offset}").json()
            for s in shipments:
                sid = s["id"]
                subs = self._req("GET", f"/shipment_subscribers?shipment_id=eq.{sid}&active=eq.1&select=telegram_id").json()
                s["subscribers_count"] = len(subs)
                chain = self._req("GET", f"/shipment_tracking_numbers?shipment_id=eq.{sid}&select=*&order=id.asc").json()
                s["tracking_chain"] = chain
                s["latest_event"] = self.get_latest_event_for_tracking(s["primary_tracking_number"])
            return shipments
        except Exception as e:
            logger.error("get_all_shipments_admin error: %s", e)
            return []

    def set_user_ban_status(self, telegram_id: int, is_banned: bool) -> bool:
        try:
            res = self._req("PATCH", f"/users?telegram_id=eq.{telegram_id}", json={"is_banned": 1 if is_banned else 0})
            return len(res.json()) > 0
        except Exception:
            return False

    def is_user_banned(self, telegram_id: int) -> bool:
        try:
            res = self.client.get(f"/users?telegram_id=eq.{telegram_id}&select=is_banned&limit=1")
            if res.status_code == 200:
                data = res.json()
                return bool(data and data[0].get("is_banned") == 1)
            return False
        except Exception:
            return False

    def admin_delete_shipment(self, shipment_id: int) -> bool:
        try:
            chain = self.get_tracking_chain_numbers(shipment_id)
            if chain:
                in_filter = f"({','.join(chain)})"
                self._req("DELETE", f"/events?tracking_number=in.{in_filter}")
            self._req("DELETE", f"/shipment_subscribers?shipment_id=eq.{shipment_id}")
            self._req("DELETE", f"/shipment_tracking_numbers?shipment_id=eq.{shipment_id}")
            res = self._req("DELETE", f"/shipments?id=eq.{shipment_id}")
            return len(res.json()) > 0
        except Exception as e:
            logger.error("admin_delete_shipment error: %s", e)
            return False

    def admin_force_shipment_state(
        self,
        shipment_id: int,
        cainiao_enabled: Optional[int] = None,
        bdpost_enabled: Optional[int] = None,
        handover_detected: Optional[int] = None,
        is_delivered: Optional[int] = None
    ) -> bool:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        payload = {"updated_at": now}
        if cainiao_enabled is not None:
            payload["cainiao_enabled"] = cainiao_enabled
        if bdpost_enabled is not None:
            payload["bdpost_enabled"] = bdpost_enabled
        if handover_detected is not None:
            payload["handover_detected"] = handover_detected
        if is_delivered is not None:
            payload["is_delivered"] = is_delivered

        try:
            res = self._req("PATCH", f"/shipments?id=eq.{shipment_id}", json=payload)
            if is_delivered == 1:
                self._req("PATCH", f"/shipment_subscribers?shipment_id=eq.{shipment_id}", json={"active": 0})
            return len(res.json()) > 0
        except Exception as e:
            logger.error("admin_force_shipment_state error: %s", e)
            return False

    def get_all_registered_telegram_ids(self) -> List[int]:
        try:
            res = self._req("GET", "/users?select=telegram_id").json()
            return [r["telegram_id"] for r in res]
        except Exception:
            return []
