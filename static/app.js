const config = window.APP_CONFIG || {
    defaultCoin: "bitcoin",
    defaultCurrency: "usd",
};

const form = document.getElementById("search-form");
const coinInput = document.getElementById("coin-input");
const searchButton = document.querySelector(".search-button");
const statusText = document.getElementById("status-text");
const coinTitle = document.getElementById("coin-title");
const priceValue = document.getElementById("price-value");
const changeValue = document.getElementById("change-value");
const volumeValue = document.getElementById("volume-value");
const capValue = document.getElementById("cap-value");
const updatedText = document.getElementById("updated-text");

let refreshTimer = null;
let currentCoin = config.defaultCoin;

function setStatus(message, isError = false) {
    statusText.textContent = message;
    statusText.classList.toggle("error", isError);
}

function formatMoney(value, currency) {
    if (typeof value !== "number") return "N/A";
    return new Intl.NumberFormat(undefined, {
        style: "currency",
        currency: currency.toUpperCase(),
        notation: value > 999999999 ? "compact" : "standard",
        maximumFractionDigits: 2,
    }).format(value);
}

function formatChange(value) {
    if (typeof value !== "number") return "N/A";
    return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function applyTrendClass(element, value) {
    element.classList.remove("positive", "negative");
    if (typeof value !== "number") return;
    element.classList.add(value >= 0 ? "positive" : "negative");
}

function renderData(data) {
    const currency = data.currency || config.defaultCurrency;
    coinTitle.textContent = `${data.coin} / ${currency}`;
    priceValue.textContent = formatMoney(data.price, currency);
    changeValue.textContent = formatChange(data.change_24h);
    volumeValue.textContent = formatMoney(data.volume_24h, currency);
    capValue.textContent = formatMoney(data.market_cap, currency);

    applyTrendClass(changeValue, data.change_24h);

    if (typeof data.provider_updated_at === "number") {
        const providerTime = new Date(data.provider_updated_at * 1000).toLocaleTimeString();
        updatedText.textContent = `Provider update: ${providerTime}`;
    } else {
        updatedText.textContent = "";
    }

    setStatus(`Live data loaded for ${data.coin}`);
}

async function fetchMarketData() {
    const query = new URLSearchParams({
        coin: currentCoin,
        currency: config.defaultCurrency,
    });

    setStatus("Latest market data load ho rahi hai...");

    try {
        const response = await fetch(`/api/market?${query.toString()}`);
        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || "Market data fetch nahi ho saki.");
        }
        renderData(data);
    } catch (error) {
        setStatus(error.message, true);
    }
}

function restartAutoRefresh() {
    if (refreshTimer) {
        clearInterval(refreshTimer);
    }
    refreshTimer = setInterval(fetchMarketData, 30000);
}

form.addEventListener("submit", (event) => {
    event.preventDefault();
    const value = coinInput.value.trim().toLowerCase();
    currentCoin = value || config.defaultCoin;
    if (searchButton) {
        searchButton.classList.add("pulse");
        setTimeout(() => searchButton.classList.remove("pulse"), 3000);
    }
    fetchMarketData();
    restartAutoRefresh();
});

fetchMarketData();
restartAutoRefresh();
