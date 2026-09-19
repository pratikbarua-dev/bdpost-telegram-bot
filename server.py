import os
import asyncio
import logging
from typing import Optional, Dict, Any, List
from aiohttp import web

from bdpost.validator import validate_and_normalize_tracking_number
from bdpost.parser import is_delivered, is_bdpost_handover_event, get_latest_event
from bdpost.formatter import get_delivery_channel_badge, get_status_smart_insight
from bdpost.directory import search_post_offices, match_location_to_post_office

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# CORS Middleware
# ------------------------------------------------------------------
@web.middleware
async def cors_middleware(request: web.Request, handler):
    if request.method == "OPTIONS":
        response = web.Response(status=204)
    else:
        try:
            response = await handler(request)
        except web.HTTPException as ex:
            response = ex

    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With"
    return response


# ------------------------------------------------------------------
# Uptime / Health Endpoints
# ------------------------------------------------------------------
async def handle_ping(request: web.Request) -> web.Response:
    return web.json_response({
        "status": "pong",
        "service": "bdpost-telegram-bot",
        "healthy": True
    }, status=200)


async def handle_health(request: web.Request) -> web.Response:
    return web.Response(text="Bangladesh Post & Cainiao Tracking System is running OK", status=200)


# ------------------------------------------------------------------
# API Documentation Root
# ------------------------------------------------------------------
async def handle_api_root(request: web.Request) -> web.Response:
    return web.json_response({
        "service": "Bangladesh Post & Cainiao Logistics Tracking API",
        "version": "2.0.0",
        "endpoints": {
            "track_parcel": {
                "method": "GET",
                "path": "/api/track/{tracking_number}",
                "description": "Track any Cainiao / AliExpress / UPU / BD Post package with chain discovery",
                "example": "/api/track/BR006144481MG"
            },
            "postcode_search": {
                "method": "GET",
                "path": "/api/postcode?query={district_or_postcode_or_thana}",
                "description": "Search Bangladesh Post Office directory with phone numbers and postcodes",
                "example": "/api/postcode?query=mirpur"
            },
            "health_ping": {
                "method": "GET",
                "path": "/ping",
                "description": "Uptime and service health check"
            }
        }
    }, status=200)


# ------------------------------------------------------------------
# Tracking API Endpoint
# ------------------------------------------------------------------
async def handle_api_track(request: web.Request) -> web.Response:
    """
    GET /api/track/{tracking_number} or GET /api/track?number={tracking_number}
    Returns complete parsed tracking events, chain discovery, carrier identification,
    delivery channel, and latest status.
    """
    raw_number = request.match_info.get("tracking_number") or request.query.get("number")
    if not raw_number:
        return web.json_response({
            "success": False,
            "error": "Missing tracking number. Provide in URL path /api/track/{number} or query ?number={number}"
        }, status=400)

    normalized_number = validate_and_normalize_tracking_number(raw_number)
    if not normalized_number:
        return web.json_response({
            "success": False,
            "error": f"Invalid tracking number format: '{raw_number}'. Must contain at least 4 digits and valid logistics prefix."
        }, status=400)

    db = request.app.get("db")

    try:
        from handlers.tracking import discover_and_fetch_chain

        # If db is available, discover full chain from DB and carriers
        if db is not None:
            shipment = db.get_shipment_by_tracking_number(normalized_number)
            sid = shipment["id"] if shipment else None
            cainiao_events, bdpost_events, chain_numbers, local_num = await discover_and_fetch_chain(
                db, normalized_number, shipment_id=sid
            )
            # Save any new events to cache
            all_events = cainiao_events + bdpost_events
            if all_events:
                try:
                    db.save_events(normalized_number, all_events)
                except Exception:
                    pass
        else:
            # Standalone carrier queries
            from cainiao.client import track as track_cainiao
            from cainiao.parser import parse_tracking_response as parse_cainiao, extract_linked_tracking_numbers
            from bdpost.client import track as track_bdpost
            from bdpost.parser import parse_tracking_response as parse_bdpost

            cainiao_events: List[Dict[str, Any]] = []
            bdpost_events: List[Dict[str, Any]] = []
            chain_numbers = [normalized_number]
            local_num = None

            c_task = track_cainiao(normalized_number)
            is_bdpost_candidate = not (normalized_number.startswith("CNG") or normalized_number.startswith("AP"))
            tasks = [c_task]
            if is_bdpost_candidate:
                tasks.append(track_bdpost(normalized_number))

            res = await asyncio.gather(*tasks, return_exceptions=True)
            if len(res) > 0 and isinstance(res[0], dict):
                cainiao_events = parse_cainiao(res[0])
                for link in extract_linked_tracking_numbers(res[0], normalized_number):
                    if link["tracking_number"] not in chain_numbers:
                        chain_numbers.append(link["tracking_number"])
            if len(res) > 1 and isinstance(res[1], str):
                bdpost_events = parse_bdpost(res[1])
                if bdpost_events:
                    local_num = normalized_number

        all_events = cainiao_events + bdpost_events
        all_events.sort(key=lambda x: str(x.get("event_date", "")))

        # Determine primary carrier
        if bdpost_events:
            primary_carrier = "Bangladesh Post"
        elif cainiao_events:
            primary_carrier = "AliExpress / Cainiao"
        else:
            primary_carrier = "Unknown / Awaiting First Scan"

        latest_bdpost = get_latest_event(bdpost_events)
        latest_cainiao = get_latest_event(cainiao_events)
        latest_event = latest_bdpost or latest_cainiao

        has_handover = any(is_bdpost_handover_event(e) for e in bdpost_events)
        parcel_delivered = bool(latest_bdpost and is_delivered(latest_bdpost.get("status", "")))

        delivery_channel = get_delivery_channel_badge(normalized_number, chain_numbers)
        # Strip HTML tags from badge for clean JSON
        delivery_channel_clean = (
            delivery_channel.replace("<b>", "").replace("</b>", "")
            .replace("🚚 ", "").replace("📮 ", "").replace("Delivery Channel: ", "")
        )

        origin_country = None
        destination_country = None
        for e in all_events:
            if e.get("origin_country"):
                origin_country = e["origin_country"]
            if e.get("destination_country"):
                destination_country = e["destination_country"]

        # Clean serialized events
        formatted_events = []
        for e in all_events:
            formatted_events.append({
                "date": e.get("event_date"),
                "status": e.get("status"),
                "description": e.get("description"),
                "location": e.get("location") or None,
                "source": e.get("source"),
                "action_code": e.get("action_code") or None,
                "timezone": e.get("timezone") or None
            })

        latest_payload = None
        if latest_event:
            latest_payload = {
                "date": latest_event.get("event_date"),
                "status": latest_event.get("status"),
                "description": latest_event.get("description"),
                "location": latest_event.get("location") or None,
                "source": latest_event.get("source")
            }

        return web.json_response({
            "success": True,
            "tracking_number": normalized_number,
            "carrier": primary_carrier,
            "delivery_channel": delivery_channel_clean,
            "is_delivered": parcel_delivered,
            "handover_detected": has_handover,
            "local_tracking_number": local_num,
            "tracking_chain": chain_numbers,
            "route": {
                "origin": origin_country,
                "destination": destination_country
            },
            "latest_status": latest_payload,
            "events_count": len(formatted_events),
            "events": formatted_events
        }, status=200)

    except Exception as e:
        logger.error("API tracking error for %s: %s", normalized_number, e, exc_info=True)
        return web.json_response({
            "success": False,
            "tracking_number": normalized_number,
            "error": f"Failed to retrieve tracking data: {str(e)}"
        }, status=502)


# ------------------------------------------------------------------
# Postcode & Office Directory API Endpoint
# ------------------------------------------------------------------
async def handle_api_postcode(request: web.Request) -> web.Response:
    """
    GET /api/postcode?query={term}&limit=20
    Returns matching post offices, districts, divisions, and direct office phone numbers.
    """
    query = request.query.get("query", "").strip()
    if not query:
        return web.json_response({
            "success": False,
            "error": "Missing 'query' parameter (e.g. /api/postcode?query=mirpur or /api/postcode?query=1216)"
        }, status=400)

    try:
        limit = min(50, max(1, int(request.query.get("limit", "20"))))
    except ValueError:
        limit = 20

    results = search_post_offices(query, limit=limit)
    return web.json_response({
        "success": True,
        "query": query,
        "count": len(results),
        "post_offices": results
    }, status=200)


# ------------------------------------------------------------------
# Server Runner
# ------------------------------------------------------------------
async def start_health_server(db: Any = None, port: int = None) -> None:
    """
    Runs the aiohttp Web and REST API server on the PORT assigned by Render/hosting provider.
    """
    if port is None:
        port = int(os.getenv("PORT", "10000"))

    app = web.Application(middlewares=[cors_middleware])
    app["db"] = db

    # Health endpoints
    app.router.add_get("/", handle_health)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/ping", handle_ping)

    # API endpoints
    app.router.add_get("/api", handle_api_root)
    app.router.add_get("/api/track", handle_api_track)
    app.router.add_get("/api/track/{tracking_number}", handle_api_track)
    app.router.add_get("/api/postcode", handle_api_postcode)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("Tracking REST API server running on port %d with endpoints: /api, /api/track/{number}, /api/postcode", port)
