                VALUES(?,?,?,?,?,?,?)
            """, (sender_id, recipient_id, currency, float(amount), "transfer", "Внутренний перевод", utc_now()))
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    return {"success": True, "amount": money(amount), "currency": currency, "to": recipient["wallet_address"]}


async def api_send(request: web.Request) -> web.Response:
    telegram_user, _ = await authenticated_request(request, require_session=True)
    body = await request.json()
    amount = decimal_value(body.get("amount"))
    currency = str(body.get("currency", "TNC")).upper()
    address = str(body.get("to_address") or body.get("to") or "")
    result = await perform_transfer(int(telegram_user["id"]), address, amount, currency)
    return web.json_response(result)


async def api_swap(request: web.Request) -> web.Response:
    # The project currently has no declared exchange rate. Do not fabricate one
    # or silently mint assets. This endpoint is intentionally disabled.
    await authenticated_request(request, require_session=True)
    raise web.HTTPNotImplemented(text="Внутренний обмен пока не настроен. Средства не списаны.")


async def api_options(request: web.Request) -> web.Response:
    return web.Response(status=204)


@web.middleware
async def cors_middleware(request: web.Request, handler):
    origin = request.headers.get("Origin")
    if request.method == "OPTIONS":
        response = web.Response(status=204)
    else:
        try:
            response = await handler(request)
        except web.HTTPException as exc:
            response = exc
    if origin and (origin in API_ALLOWED_ORIGINS or origin == request.scheme + "://" + request.host):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Wallet-Session, X-Telegram-Init-Data"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


async def serve_webapp(request: web.Request) -> web.StreamResponse:
    path = Path(__file__).resolve().parent / "webapp" / "index.html"
    if not path.is_file():
        return web.Response(
            text="TOKENS Mini App: файл webapp/index.html не найден. Загрузите index.html в папку webapp.",
            content_type="text/plain", status=200,
        )
    return web.FileResponse(path)


def build_web_app() -> web.Application:
    app = web.Application(middlewares=[cors_middleware], client_max_size=64 * 1024)
    app.router.add_get("/health", lambda request: web.json_response({"ok": True, "service": "TOKENS"}))
    app.router.add_get("/webapp/", serve_webapp)
    app.router.add_get("/webapp/index.html", serve_webapp)
    app.router.add_post("/api/pin/status", api_pin_status)
    app.router.add_post("/api/pin/setup", api_pin_setup)
    app.router.add_post("/api/pin/verify", api_pin_verify)
    app.router.add_post("/api/user", api_user)
    app.router.add_post("/api/send", api_send)
    app.router.add_post("/api/transfer", api_send)
    app.router.add_post("/api/swap", api_swap)
    app.router.add_route("OPTIONS", "/{tail:.*}", api_options)
    webapp_dir = Path(__file__).resolve().parent / "webapp"
    webapp_dir.mkdir(parents=True, exist_ok=True)
    # Keep static serving enabled for assets (the explicit index routes above
    # take precedence for the main document).
    app.router.add_static("/webapp/", str(webapp_dir), show_index=True, name="webapp-static")
    return app


async def start_web_server() -> web.AppRunner:
    app = build_web_app()
    runner = web.AppRunner(app, access_log=log)
    await runner.setup()
    site = web.TCPSite(runner, HOST, PORT)
    await site.start()
    log.info("HTTP server listening on %s:%s", HOST, PORT)
    return runner


@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    if message.from_user is None:
        return
    user = {
        "id": message.from_user.id,
        "username": message.from_user.username,
        "first_name": message.from_user.first_name,
    }
    await ensure_user(user)
    if WEBAPP_URL:
        keyboard = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="🚀 Открыть TOKENS Wallet", web_app=WebAppInfo(url=WEBAPP_URL))]],
            resize_keyboard=True,
            is_persistent=True,
        )
        await message.answer(
            "Добро пожаловать в <b>TOKENS</b>!\n\n"
            "Это демонстрационный внутренний кошелёк TOKENS / TNC. Балансы не являются реальной криптовалютой и не работают в блокчейне.\n\n"
            "Открой приложение, чтобы создать PIN и посмотреть кошелёк.",
            reply_markup=keyboard,
        )
    else:
        await message.answer("Задайте WEBAPP_URL в переменных окружения.")


async def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("Не задан BOT_TOKEN в переменных окружения")
    await init_db()
    runner = await start_web_server()
    try:
        assert bot is not None
        await dp.start_polling(bot, close_bot_session=False)
    finally:
        await runner.cleanup()
        if bot is not None:
            await bot.session.close()
