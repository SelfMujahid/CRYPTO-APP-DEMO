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
    const statusText = document.getElementById("home-status");
    const tableBody = document.getElementById("market-table-body");

    if (!currencySelect || !searchInput || !refreshButton || !statusText || !tableBody) return;

    let allMarkets = [];

    const renderRows = (markets) => {
        tableBody.innerHTML = "";
        markets.forEach((coin, idx) => {
            const change = toSafeNumber(coin.price_change_percentage_24h);
            const row = document.createElement("tr");
            row.innerHTML = `
                <td>${idx + 1}</td>
                <td>
                    <div class="coin-cell">
                        <img src="${coin.image || ""}" alt="${coin.symbol || "coin"}">
                        <div>
                            <strong>${coin.name || "-"}</strong><br>
                            <small>${(coin.symbol || "").toUpperCase()}</small>
                        </div>
                    </div>
                </td>
                <td>${fmtMoney(toSafeNumber(coin.current_price), currencySelect.value)}</td>
                <td class="${change >= 0 ? "positive" : "negative"}">${fmtPercent(change)}</td>
                <td>${fmtMoney(toSafeNumber(coin.total_volume), currencySelect.value)}</td>
                <td>${fmtMoney(toSafeNumber(coin.market_cap), currencySelect.value)}</td>
            `;
            tableBody.appendChild(row);
        });
    };

    const applyFilter = () => {
        const query = searchInput.value.trim().toLowerCase();
        if (!query) {
            renderRows(allMarkets);
            return;
        }
        const filtered = allMarkets.filter((item) => {
            const name = (item.name || "").toLowerCase();
            const symbol = (item.symbol || "").toLowerCase();
            return name.includes(query) || symbol.includes(query);
        });
        renderRows(filtered);
    };

    const loadMarkets = async () => {
        setMessage(statusText, "All crypto market load ho raha hai...");
        try {
            const data = await requestJSON(`/api/markets?currency=${encodeURIComponent(currencySelect.value)}&limit=100`);
            allMarkets = Array.isArray(data.markets) ? data.markets : [];
            applyFilter();
            setMessage(statusText, `Updated: ${new Date().toLocaleTimeString()}`);
        } catch (error) {
            setMessage(statusText, error.message, true);
        }
    };

    currencySelect.addEventListener("change", loadMarkets);
    searchInput.addEventListener("input", applyFilter);
    refreshButton.addEventListener("click", loadMarkets);

    loadMarkets();
    setInterval(loadMarkets, 30000);
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

function initTradingHome() {
    const balanceEl = document.getElementById("demo-balance");
    const statusEl = document.getElementById("trading-status");
    fetchAccountAndRender(balanceEl, statusEl);
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
        } catch (error) {
            setMessage(statusEl, error.message, true);
        }
    });

    coinInput.addEventListener("change", refreshTicker);
    loadBalance();
    refreshTicker();
    setInterval(refreshTicker, 25000);
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
                openPositionEl.textContent = `Open Position: ${data.open_position.side.toUpperCase()} ${data.open_position.coin.toUpperCase()} @ ${data.open_position.entry_price}`;
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
    setInterval(refreshBotStatus, 5000);
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
