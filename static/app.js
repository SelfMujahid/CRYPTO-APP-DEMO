const config = window.APP_CONFIG || {};
const page = config.page || document.body.dataset.page || "base";

const defaultCurrency = (config.defaultCurrency || "usd").toLowerCase();
const defaultCoin = (config.defaultCoin || "bitcoin").toLowerCase();

function fmtMoney(value, currency = "usd") {
    if (typeof value !== "number" || !Number.isFinite(value)) return "N/A";
    return new Intl.NumberFormat(undefined, {
        style: "currency",
        currency: currency.toUpperCase(),
        notation: value >= 1_000_000_000 ? "compact" : "standard",
        maximumFractionDigits: 2,
    }).format(value);
}

function fmtMaybeMoney(value, currency = "usd") {
    if (typeof value !== "number" || !Number.isFinite(value)) return "-";
    return fmtMoney(value, currency);
}

function fmtPercent(value) {
    if (typeof value !== "number" || !Number.isFinite(value)) return "N/A";
    return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function toSafeNumber(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
}

async function requestJSON(url, options = {}) {
    const response = await fetch(url, options);
    let data = {};
    try {
        data = await response.json();
    } catch (error) {
        data = {};
    }
    if (!response.ok) {
        throw new Error(data.error || `Request failed (${response.status})`);
    }
    return data;
}

function setMessage(element, text, isError = false) {
    if (!element) return;
    element.textContent = text;
    element.classList.toggle("error", isError);
}

function renderBookRows(container, midPrice) {
    if (!container) return;
    container.innerHTML = "";
    const safeMid = Number.isFinite(midPrice) && midPrice > 0 ? midPrice : 1;

    for (let index = 0; index < 8; index += 1) {
        const spreadPct = (index + 1) * 0.12;
        const ask = safeMid * (1 + spreadPct / 100);
        const bid = safeMid * (1 - spreadPct / 100);

        const row = document.createElement("div");
        row.className = "book-row";
        row.innerHTML = `
            <span>Ask: ${ask.toFixed(4)}</span>
            <span>Bid: ${bid.toFixed(4)}</span>
            <span>Spread: ${spreadPct.toFixed(2)}%</span>
        `;
        container.appendChild(row);
    }
}

function initHomePage() {
    const currencySelect = document.getElementById("currency-select");
    const searchInput = document.getElementById("market-search");
    const refreshButton = document.getElementById("refresh-markets");
    const loadMoreButton = document.getElementById("load-more-coins");
    const statusText = document.getElementById("home-status");
    const tableBody = document.getElementById("market-table-body");

    if (!currencySelect || !searchInput || !refreshButton || !statusText || !tableBody || !loadMoreButton) return;

    let allMarkets = [];
    let allCoins = [];
    let hasLoadedCoins = false;
    let visibleLimit = 600;

    const renderRows = (coins) => {
        tableBody.innerHTML = "";
        coins.forEach((coin) => {
            const change = toSafeNumber(coin.price_change_percentage_24h);
            const rawPrice = coin.current_price;
            const rawVolume = coin.total_volume;
            const rawCap = coin.market_cap;
            const showChange = typeof coin.price_change_percentage_24h === "number";
            const rank = Number.isFinite(Number(coin.market_cap_rank)) ? Number(coin.market_cap_rank) : "-";
            const iconHtml = coin.image
                ? `<img src="${coin.image}" alt="${coin.symbol || "coin"}">`
                : `<span class="coin-fallback">${String((coin.symbol || coin.name || "?")[0] || "?").toUpperCase()}</span>`;

            const row = document.createElement("tr");
            row.innerHTML = `
                <td>${rank}</td>
                <td>
                    <div class="coin-cell">
                        ${iconHtml}
                        <div>
                            <strong>${coin.name || "-"}</strong><br>
                            <small>${(coin.symbol || "").toUpperCase()} ${coin.id ? `| ${coin.id}` : ""}</small>
                        </div>
                    </div>
                </td>
                <td>${fmtMaybeMoney(rawPrice, currencySelect.value)}</td>
                <td class="${showChange ? (change >= 0 ? "positive" : "negative") : ""}">${showChange ? fmtPercent(change) : "-"}</td>
                <td>${fmtMaybeMoney(rawVolume, currencySelect.value)}</td>
                <td>${fmtMaybeMoney(rawCap, currencySelect.value)}</td>
            `;
            tableBody.appendChild(row);
        });
    };

    const applyFilter = () => {
        const query = searchInput.value.trim().toLowerCase();
        const marketsMap = new Map();
        allMarkets.forEach((item) => {
            if (item && item.id) {
                marketsMap.set(item.id, item);
            }
        });

        let filteredCoins = allCoins;
        if (query) {
            filteredCoins = allCoins.filter((item) => {
                const name = (item.name || "").toLowerCase();
                const symbol = (item.symbol || "").toLowerCase();
                const id = (item.id || "").toLowerCase();
                return name.includes(query) || symbol.includes(query) || id.includes(query);
            });
        }

        const merged = filteredCoins.map((coin) => {
            const market = marketsMap.get(coin.id) || {};
            return {
                ...coin,
                image: market.image || "",
                market_cap_rank: market.market_cap_rank,
                current_price: market.current_price,
                total_volume: market.total_volume,
                market_cap: market.market_cap,
                price_change_percentage_24h: market.price_change_percentage_24h,
            };
        });

        merged.sort((a, b) => {
            const rankA = Number.isFinite(Number(a.market_cap_rank)) ? Number(a.market_cap_rank) : Number.MAX_SAFE_INTEGER;
            const rankB = Number.isFinite(Number(b.market_cap_rank)) ? Number(b.market_cap_rank) : Number.MAX_SAFE_INTEGER;
            if (rankA !== rankB) return rankA - rankB;
            return String(a.name || "").localeCompare(String(b.name || ""));
        });

        const limited = merged.slice(0, visibleLimit);
        renderRows(limited);

        if (merged.length > visibleLimit) {
            loadMoreButton.style.display = "inline-block";
            loadMoreButton.textContent = `Load More (${Math.min(600, merged.length - visibleLimit)} more)`;
        } else {
            loadMoreButton.style.display = "none";
        }

        if (query) {
            setMessage(statusText, `Results: ${merged.length} | Showing: ${limited.length}`);
        } else {
            setMessage(statusText, `All coins loaded: ${allCoins.length} | Showing: ${limited.length}`);
        }
    };

    const loadCoins = async () => {
        if (hasLoadedCoins) return;
        setMessage(statusText, "All coins directory load ho rahi hai...");
        try {
            const data = await requestJSON("/api/coins");
            allCoins = Array.isArray(data.coins) ? data.coins : [];
            hasLoadedCoins = true;
            applyFilter();
        } catch (error) {
            setMessage(statusText, error.message, true);
        }
    };

    const loadMarkets = async () => {
        setMessage(statusText, "Ranked market prices load ho rahi hain...");
        try {
            const data = await requestJSON(`/api/markets/ranked?currency=${encodeURIComponent(currencySelect.value)}&pages=4&per_page=250`);
            allMarkets = Array.isArray(data.markets) ? data.markets : [];
            if (!hasLoadedCoins) {
                await loadCoins();
            } else {
                applyFilter();
            }
        } catch (error) {
            setMessage(statusText, error.message, true);
        }
    };

    currencySelect.addEventListener("change", loadMarkets);
    searchInput.addEventListener("input", () => {
        visibleLimit = 600;
        applyFilter();
    });
    refreshButton.addEventListener("click", loadMarkets);
    loadMoreButton.addEventListener("click", () => {
        visibleLimit += 600;
        applyFilter();
    });

    loadMarkets();
    setInterval(loadMarkets, 120000);
}

async function fetchAccountAndRender(balanceElement, statusElement) {
    if (!balanceElement) return;
    try {
        const account = await requestJSON("/api/account");
        balanceElement.textContent = fmtMoney(toSafeNumber(account.balance_usd), "usd");
        if (statusElement) setMessage(statusElement, "Demo account synced.");
    } catch (error) {
        if (statusElement) setMessage(statusElement, error.message, true);
    }
}

function formatTradePnlCell(value) {
    const numeric = toSafeNumber(value);
    return `<span class="${numeric >= 0 ? "positive" : "negative"}">${fmtMoney(numeric, "usd")}</span>`;
}

function renderRunningTradesTable(tbody, tradeStatus) {
    if (!tbody) return;
    tbody.innerHTML = "";

    const futures = Array.isArray(tradeStatus.futures_positions) ? tradeStatus.futures_positions : [];
    const botPosition = tradeStatus.bot_open_position;

    if (!futures.length && !botPosition) {
        const row = document.createElement("tr");
        row.innerHTML = "<td colspan='8'>No running trades.</td>";
        tbody.appendChild(row);
        return;
    }

    futures.forEach((position) => {
        const pnlPct = toSafeNumber(position.pnl_pct);
        const row = document.createElement("tr");
        row.innerHTML = `
            <td>Futures #${position.position_id}</td>
            <td>${String(position.coin || "").toUpperCase()}</td>
            <td>${String(position.side || "").toUpperCase()}</td>
            <td>${position.entry_price ? Number(position.entry_price).toFixed(4) : "-"}</td>
            <td>${position.current_price ? Number(position.current_price).toFixed(4) : "-"}</td>
            <td>${position.leverage || "-" }x</td>
            <td class="${pnlPct >= 0 ? "positive" : "negative"}">${fmtPercent(pnlPct)}</td>
            <td>${formatTradePnlCell(position.pnl_usd)}</td>
        `;
        tbody.appendChild(row);
    });

    if (botPosition) {
        const pnlPct = toSafeNumber(botPosition.pnl_pct);
        const row = document.createElement("tr");
        row.innerHTML = `
            <td>Bot</td>
            <td>${String(botPosition.coin || "").toUpperCase()}</td>
            <td>${String(botPosition.side || "").toUpperCase()}</td>
            <td>${botPosition.entry_price ? Number(botPosition.entry_price).toFixed(4) : "-"}</td>
            <td>${botPosition.current_price ? Number(botPosition.current_price).toFixed(4) : "-"}</td>
            <td>${botPosition.leverage || "-" }x</td>
            <td class="${pnlPct >= 0 ? "positive" : "negative"}">${fmtPercent(pnlPct)}</td>
            <td>${formatTradePnlCell(botPosition.pnl_usd)}</td>
        `;
        tbody.appendChild(row);
    }
}

function initTradingHome() {
    const balanceEl = document.getElementById("demo-balance");
    const statusEl = document.getElementById("trading-status");
    const runningBody = document.getElementById("running-trades-body");

    const refresh = async () => {
        await fetchAccountAndRender(balanceEl, statusEl);
        try {
            const tradeStatus = await requestJSON("/api/trade/status");
            renderRunningTradesTable(runningBody, tradeStatus);
        } catch (error) {
            setMessage(statusEl, error.message, true);
        }
    };

    refresh();
    setInterval(refresh, 10000);
}

function initSpotPage() {
    const coinInput = document.getElementById("spot-coin");
    const sideSelect = document.getElementById("spot-side");
    const amountInput = document.getElementById("spot-amount");
    const form = document.getElementById("spot-form");
    const symbolEl = document.getElementById("spot-symbol");
    const priceEl = document.getElementById("spot-price");
    const changeEl = document.getElementById("spot-change");
    const bookEl = document.getElementById("spot-book");
    const statusEl = document.getElementById("spot-status");
    const balanceEl = document.getElementById("spot-balance");

    if (!coinInput || !sideSelect || !amountInput || !form) return;

    const refreshTicker = async () => {
        const coin = (coinInput.value.trim().toLowerCase() || defaultCoin);
        try {
            const market = await requestJSON(`/api/market?coin=${encodeURIComponent(coin)}&currency=${defaultCurrency}`);
            symbolEl.textContent = `${coin.toUpperCase()}/${defaultCurrency.toUpperCase()}`;
            priceEl.textContent = `Price: ${fmtMoney(toSafeNumber(market.price), defaultCurrency)}`;
            const changeValue = toSafeNumber(market.change_24h);
            changeEl.textContent = `24h change: ${fmtPercent(changeValue)}`;
            changeEl.classList.remove("positive", "negative");
            changeEl.classList.add(changeValue >= 0 ? "positive" : "negative");
            renderBookRows(bookEl, toSafeNumber(market.price));
        } catch (error) {
            setMessage(changeEl, error.message, true);
        }
    };

    const loadBalance = async () => {
        try {
            const account = await requestJSON("/api/account");
            balanceEl.textContent = `Demo Balance: ${fmtMoney(toSafeNumber(account.balance_usd), "usd")}`;
        } catch (error) {
            balanceEl.textContent = `Demo Balance: ${error.message}`;
        }
    };

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const coin = coinInput.value.trim().toLowerCase() || defaultCoin;
        const side = sideSelect.value;
        const amount = toSafeNumber(amountInput.value);

        setMessage(statusEl, "Spot order place ho raha hai...");
        try {
            const result = await requestJSON("/api/trade/execute", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    market_type: "spot",
                    coin,
                    currency: defaultCurrency,
                    side,
                    amount_usd: amount,
                }),
            });
            setMessage(
                statusEl,
                `Spot ${side} order filled: ${coin.toUpperCase()} ${fmtMoney(toSafeNumber(result.trade.amount_usd), "usd")}`
            );
            balanceEl.textContent = `Demo Balance: ${fmtMoney(toSafeNumber(result.balance_usd), "usd")}`;
            refreshTicker();
        } catch (error) {
            setMessage(statusEl, error.message, true);
        }
    });

    coinInput.addEventListener("change", refreshTicker);
    loadBalance();
    refreshTicker();
    setInterval(refreshTicker, 25000);
}

function initFuturesPage() {
    const coinInput = document.getElementById("futures-coin");
    const sideSelect = document.getElementById("futures-side");
    const amountInput = document.getElementById("futures-amount");
    const leverageInput = document.getElementById("futures-leverage");
    const form = document.getElementById("futures-form");
    const symbolEl = document.getElementById("futures-symbol");
    const priceEl = document.getElementById("futures-price");
    const changeEl = document.getElementById("futures-change");
    const bookEl = document.getElementById("futures-book");
    const statusEl = document.getElementById("futures-status");
    const balanceEl = document.getElementById("futures-balance");
    const openBody = document.getElementById("futures-open-body");

    if (!coinInput || !sideSelect || !amountInput || !leverageInput || !form) return;

    const refreshTicker = async () => {
        const coin = (coinInput.value.trim().toLowerCase() || defaultCoin);
        try {
            const market = await requestJSON(`/api/market?coin=${encodeURIComponent(coin)}&currency=${defaultCurrency}`);
            symbolEl.textContent = `${coin.toUpperCase()}/${defaultCurrency.toUpperCase()}`;
            priceEl.textContent = `Mark Price: ${fmtMoney(toSafeNumber(market.price), defaultCurrency)}`;
            const changeValue = toSafeNumber(market.change_24h);
            changeEl.textContent = `24h change: ${fmtPercent(changeValue)}`;
            changeEl.classList.remove("positive", "negative");
            changeEl.classList.add(changeValue >= 0 ? "positive" : "negative");
            renderBookRows(bookEl, toSafeNumber(market.price));
        } catch (error) {
            setMessage(changeEl, error.message, true);
        }
    };

    const loadBalance = async () => {
        try {
            const account = await requestJSON("/api/account");
            balanceEl.textContent = `Demo Balance: ${fmtMoney(toSafeNumber(account.balance_usd), "usd")}`;
        } catch (error) {
            balanceEl.textContent = `Demo Balance: ${error.message}`;
        }
    };

    const renderOpenPositions = (positions) => {
        if (!openBody) return;
        openBody.innerHTML = "";

        if (!positions.length) {
            const row = document.createElement("tr");
            row.innerHTML = "<td colspan='8'>No open futures positions.</td>";
            openBody.appendChild(row);
            return;
        }

        positions.forEach((position) => {
            const pnlPct = toSafeNumber(position.pnl_pct);
            const row = document.createElement("tr");
            row.innerHTML = `
                <td>${position.position_id}</td>
                <td>${String(position.coin || "").toUpperCase()}</td>
                <td>${String(position.side || "").toUpperCase()}</td>
                <td>${position.entry_price ? Number(position.entry_price).toFixed(4) : "-"}</td>
                <td>${position.current_price ? Number(position.current_price).toFixed(4) : "-"}</td>
                <td class="${pnlPct >= 0 ? "positive" : "negative"}">${fmtPercent(pnlPct)}</td>
                <td class="${toSafeNumber(position.pnl_usd) >= 0 ? "positive" : "negative"}">${fmtMoney(toSafeNumber(position.pnl_usd), "usd")}</td>
                <td><button class="danger-btn close-position-btn" data-position-id="${position.position_id}">Close</button></td>
            `;
            openBody.appendChild(row);
        });
    };

    const refreshPositions = async () => {
        try {
            const status = await requestJSON("/api/trade/status");
            renderOpenPositions(status.futures_positions || []);
            balanceEl.textContent = `Demo Balance: ${fmtMoney(toSafeNumber(status.balance_usd), "usd")}`;
        } catch (error) {
            setMessage(statusEl, error.message, true);
        }
    };

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const coin = coinInput.value.trim().toLowerCase() || defaultCoin;
        const side = sideSelect.value;
        const amount = toSafeNumber(amountInput.value);
        const leverage = toSafeNumber(leverageInput.value);

        setMessage(statusEl, "Futures order execute ho raha hai...");
        try {
            const result = await requestJSON("/api/trade/execute", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    market_type: "futures",
                    coin,
                    currency: defaultCurrency,
                    side,
                    leverage,
                    amount_usd: amount,
                }),
            });
            setMessage(
                statusEl,
                `Futures ${side} order opened: ${coin.toUpperCase()} ${leverage}x, margin ${fmtMoney(amount, "usd")}`
            );
            balanceEl.textContent = `Demo Balance: ${fmtMoney(toSafeNumber(result.balance_usd), "usd")}`;
            refreshTicker();
            refreshPositions();
        } catch (error) {
            setMessage(statusEl, error.message, true);
        }
    });

    if (openBody) {
        openBody.addEventListener("click", async (event) => {
            const target = event.target;
            if (!(target instanceof HTMLElement)) return;
            if (!target.classList.contains("close-position-btn")) return;
            const positionId = toSafeNumber(target.dataset.positionId);
            if (!positionId) return;

            setMessage(statusEl, "Position close ho rahi hai...");
            try {
                const result = await requestJSON("/api/trade/close", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ position_id: positionId }),
                });
                setMessage(statusEl, `Position #${positionId} close ho gayi.`);
                balanceEl.textContent = `Demo Balance: ${fmtMoney(toSafeNumber(result.balance_usd), "usd")}`;
                refreshTicker();
                refreshPositions();
            } catch (error) {
                setMessage(statusEl, error.message, true);
            }
        });
    }

    coinInput.addEventListener("change", refreshTicker);
    loadBalance();
    refreshTicker();
    refreshPositions();
    setInterval(refreshTicker, 25000);
    setInterval(refreshPositions, 10000);
}

function initBotPage() {
    const form = document.getElementById("bot-form");
    const stopButton = document.getElementById("stop-bot-btn");
    const actionStatus = document.getElementById("bot-action-status");

    const coinInput = document.getElementById("bot-coin");
    const timeframeInput = document.getElementById("bot-timeframe");
    const leverageInput = document.getElementById("bot-leverage");
    const amountInput = document.getElementById("bot-amount");
    const indicatorInput = document.getElementById("bot-indicator");
    const tpInput = document.getElementById("bot-tp");
    const slInput = document.getElementById("bot-sl");

    const runningEl = document.getElementById("bot-running");
    const balanceEl = document.getElementById("bot-balance");
    const signalEl = document.getElementById("bot-signal");
    const priceEl = document.getElementById("bot-price");
    const openPositionEl = document.getElementById("bot-open-position");
    const errorEl = document.getElementById("bot-last-error");
    const tradesBody = document.getElementById("bot-trades-body");

    if (!form || !stopButton) return;

    const renderBotTrades = (trades) => {
        tradesBody.innerHTML = "";
        if (!Array.isArray(trades) || trades.length === 0) {
            const row = document.createElement("tr");
            row.innerHTML = "<td colspan='7'>No bot trades yet.</td>";
            tradesBody.appendChild(row);
            return;
        }

        trades.forEach((trade) => {
            const row = document.createElement("tr");
            const pnlPercent = toSafeNumber(trade.pnl_pct);
            row.innerHTML = `
                <td>${new Date(trade.timestamp).toLocaleTimeString()}</td>
                <td>${trade.trade_type || "-"}</td>
                <td>${(trade.coin || "-").toUpperCase()}</td>
                <td>${(trade.side || "-").toUpperCase()}</td>
                <td>${trade.entry_price ? Number(trade.entry_price).toFixed(4) : "-"}</td>
                <td>${trade.exit_price ? Number(trade.exit_price).toFixed(4) : "-"}</td>
                <td class="${pnlPercent >= 0 ? "positive" : "negative"}">${trade.pnl_pct != null ? fmtPercent(pnlPercent) : "-"}</td>
            `;
            tradesBody.appendChild(row);
        });
    };

    const refreshBotStatus = async () => {
        try {
            const data = await requestJSON("/api/bot/status");
            runningEl.textContent = data.running ? "Yes" : "No";
            balanceEl.textContent = fmtMoney(toSafeNumber(data.balance_usd), "usd");
            signalEl.textContent = (data.last_signal || "-").toUpperCase();
            priceEl.textContent = data.last_price ? fmtMoney(toSafeNumber(data.last_price), "usd") : "-";
            errorEl.textContent = data.last_error || "";

            if (data.open_position) {
                const pnlText = data.open_position.pnl_usd != null
                    ? ` | P/L: ${fmtMoney(toSafeNumber(data.open_position.pnl_usd), "usd")} (${fmtPercent(toSafeNumber(data.open_position.pnl_pct))})`
                    : "";
                openPositionEl.textContent = `Open Position: ${data.open_position.side.toUpperCase()} ${data.open_position.coin.toUpperCase()} @ ${data.open_position.entry_price}${pnlText}`;
            } else {
                openPositionEl.textContent = "Open Position: none";
            }
            renderBotTrades(data.recent_bot_trades || []);
        } catch (error) {
            setMessage(actionStatus, error.message, true);
        }
    };

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        setMessage(actionStatus, "Bot start ho raha hai...");

        const payload = {
            coin: (coinInput.value.trim().toLowerCase() || defaultCoin),
            currency: defaultCurrency,
            timeframe: timeframeInput.value,
            leverage: toSafeNumber(leverageInput.value),
            amount_usd: toSafeNumber(amountInput.value),
            indicator: indicatorInput.value,
            take_profit_pct: toSafeNumber(tpInput.value),
            stop_loss_pct: toSafeNumber(slInput.value),
        };

        try {
            const data = await requestJSON("/api/bot/start", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            setMessage(actionStatus, data.message || "Bot started.");
            refreshBotStatus();
        } catch (error) {
            setMessage(actionStatus, error.message, true);
        }
    });

    stopButton.addEventListener("click", async () => {
        setMessage(actionStatus, "Bot stop request bheji ja rahi hai...");
        try {
            const data = await requestJSON("/api/bot/stop", { method: "POST" });
            setMessage(actionStatus, data.message || "Bot stopped.");
            refreshBotStatus();
        } catch (error) {
            setMessage(actionStatus, error.message, true);
        }
    });

    refreshBotStatus();
    setInterval(refreshBotStatus, 8000);
}

function initChartPage() {
    const coinSelect = document.getElementById("chart-coin");
    const intervalSelect = document.getElementById("chart-interval");
    const refreshBtn = document.getElementById("chart-refresh");
    const statusEl = document.getElementById("chart-status");
    const tvContainer = document.getElementById("tradingview-widget");
    const canvas = document.getElementById("candlestick-canvas");

    if (!coinSelect || !intervalSelect || !refreshBtn || !statusEl || !tvContainer || !canvas) return;
    let latestCandles = [];

    const intervalToDays = (interval) => {
        const mapping = {
            "1": "1",
            "3": "1",
            "5": "1",
            "15": "1",
            "30": "1",
            "60": "7",
            "120": "7",
            "240": "30",
            D: "90",
            W: "90",
            M: "90",
        };
        return mapping[interval] || "30";
    };

    const drawCandles = (series) => {
        const ctx = canvas.getContext("2d");
        if (!ctx) return;

        const parent = canvas.parentElement;
        const width = Math.max((parent?.clientWidth || 900) - 2, 320);
        const height = Math.max((parent?.clientHeight || 520) - 2, 260);
        canvas.width = width;
        canvas.height = height;

        ctx.clearRect(0, 0, width, height);
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(0, 0, width, height);

        if (!Array.isArray(series) || series.length === 0) {
            ctx.fillStyle = "#40556d";
            ctx.font = "14px Trebuchet MS";
            ctx.fillText("No chart data available.", 16, 30);
            return;
        }

        const padLeft = 56;
        const padRight = 14;
        const padTop = 12;
        const padBottom = 28;
        const bodyWidth = Math.max((width - padLeft - padRight) / series.length * 0.65, 1.2);

        const highs = series.map((c) => Number(c.high));
        const lows = series.map((c) => Number(c.low));
        const maxPrice = Math.max(...highs);
        const minPrice = Math.min(...lows);
        const range = Math.max(maxPrice - minPrice, 1e-6);

        const yForPrice = (price) =>
            padTop + ((maxPrice - price) / range) * (height - padTop - padBottom);

        ctx.strokeStyle = "rgba(20,163,199,0.18)";
        ctx.lineWidth = 1;
        for (let i = 0; i < 5; i += 1) {
            const y = padTop + (i / 4) * (height - padTop - padBottom);
            ctx.beginPath();
            ctx.moveTo(padLeft, y);
            ctx.lineTo(width - padRight, y);
            ctx.stroke();

            const price = maxPrice - (i / 4) * range;
            ctx.fillStyle = "#556b82";
            ctx.font = "11px Trebuchet MS";
            ctx.fillText(price.toFixed(4), 6, y + 4);
        }

        series.forEach((candle, idx) => {
            const x = padLeft + (idx + 0.5) * ((width - padLeft - padRight) / series.length);
            const open = Number(candle.open);
            const high = Number(candle.high);
            const low = Number(candle.low);
            const close = Number(candle.close);

            const yOpen = yForPrice(open);
            const yHigh = yForPrice(high);
            const yLow = yForPrice(low);
            const yClose = yForPrice(close);
            const up = close >= open;
            const color = up ? "#16a34a" : "#dc2626";

            ctx.strokeStyle = color;
            ctx.beginPath();
            ctx.moveTo(x, yHigh);
            ctx.lineTo(x, yLow);
            ctx.stroke();

            const top = Math.min(yOpen, yClose);
            const bodyH = Math.max(Math.abs(yClose - yOpen), 1);
            ctx.fillStyle = color;
            ctx.fillRect(x - bodyWidth / 2, top, bodyWidth, bodyH);
        });

        const step = Math.max(Math.floor(series.length / 4), 1);
        for (let i = 0; i < series.length; i += step) {
            const x = padLeft + (i + 0.5) * ((width - padLeft - padRight) / series.length);
            const timeText = new Date((Number(series[i].time) || 0) * 1000).toLocaleDateString();
            ctx.fillStyle = "#5a7188";
            ctx.font = "10px Trebuchet MS";
            ctx.fillText(timeText, Math.max(x - 20, padLeft), height - 8);
        }
    };

    const ensureTradingViewScript = () =>
        new Promise((resolve, reject) => {
            if (window.TradingView && window.TradingView.widget) {
                resolve(true);
                return;
            }

            const existing = document.querySelector("script[data-tv-script='1']");
            if (existing) {
                existing.addEventListener("load", () => resolve(true), { once: true });
                existing.addEventListener("error", () => reject(new Error("TradingView script load fail.")), { once: true });
                return;
            }

            const script = document.createElement("script");
            script.src = "https://s3.tradingview.com/tv.js";
            script.async = true;
            script.dataset.tvScript = "1";
            script.onload = () => resolve(true);
            script.onerror = () => reject(new Error("TradingView script load fail."));
            document.head.appendChild(script);
        });

    const createTradingViewWidget = async () => {
        const selectedOption = coinSelect.options[coinSelect.selectedIndex];
        const tvSymbol = selectedOption?.dataset?.tvSymbol || "BINANCE:BTCUSDT";
        const interval = intervalSelect.value;

        await ensureTradingViewScript();
        if (!(window.TradingView && window.TradingView.widget)) {
            throw new Error("TradingView widget available nahi.");
        }

        tvContainer.innerHTML = "";
        tvContainer.style.display = "block";
        canvas.style.display = "none";

        new window.TradingView.widget({
            symbol: tvSymbol,
            interval,
            timezone: "Etc/UTC",
            theme: "light",
            style: "1",
            locale: "en",
            hide_top_toolbar: false,
            hide_side_toolbar: false,
            allow_symbol_change: true,
            enable_publishing: false,
            autosize: true,
            container_id: "tradingview-widget",
        });
    };

    const loadFallbackChart = async () => {
        const coin = coinSelect.value;
        const interval = intervalSelect.value;
        const days = intervalToDays(interval);
        setMessage(statusEl, "Fallback candlestick chart load ho raha hai...");
        try {
            const data = await requestJSON(
                `/api/ohlc?coin=${encodeURIComponent(coin)}&currency=${defaultCurrency}&days=${encodeURIComponent(days)}`
            );
            latestCandles = Array.isArray(data.candles) ? data.candles : [];
            tvContainer.style.display = "none";
            canvas.style.display = "block";
            drawCandles(latestCandles);
            setMessage(statusEl, `Fallback chart updated: ${coin.toUpperCase()} (${interval})`);
        } catch (error) {
            setMessage(statusEl, error.message, true);
        }
    };

    window.addEventListener("resize", () => drawCandles(latestCandles));

    const loadChart = async () => {
        setMessage(statusEl, "TradingView chart load ho raha hai...");
        try {
            await createTradingViewWidget();
            const coin = coinSelect.value;
            const interval = intervalSelect.value;
            setMessage(statusEl, `TradingView chart updated: ${coin.toUpperCase()} (${interval})`);
        } catch (error) {
            await loadFallbackChart();
        }
    };

    refreshBtn.addEventListener("click", loadChart);
    coinSelect.addEventListener("change", loadChart);
    intervalSelect.addEventListener("change", loadChart);

    loadChart();
    setInterval(loadChart, 120000);
}

if (page === "home") {
    initHomePage();
}
if (page === "trading-home") {
    initTradingHome();
}
if (page === "spot") {
    initSpotPage();
}
if (page === "futures") {
    initFuturesPage();
}
if (page === "bot") {
    initBotPage();
}
if (page === "chart") {
    initChartPage();
}
