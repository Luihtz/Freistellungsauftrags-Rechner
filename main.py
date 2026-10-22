import pandas as pd
import streamlit as st


RELEVANT_COLUMNS = [
    "type",
    "symbol",
    "shares",
    "price"
]


def load_transactions(file):
    """Load the Trade Republic transaction CSV."""

    df = pd.read_csv(
        file,
        skipinitialspace=True,
    )

    df.columns = df.columns.str.strip()

    df = df[RELEVANT_COLUMNS].copy()

    return df


def filter_asset(df, assets):
    """
    Keep transactions belonging to the selected ETF position.

    Multiple symbols/ISINs can belong to the same position.
    """

    if isinstance(assets, str):
        assets = [assets]

    mask = (
        df["symbol"]
        .fillna("")
        .str.lower()
        .isin([asset.lower() for asset in assets])
    )

    return df.loc[mask].copy()


def filter_buys_and_sells(df):
    """Keep only BUY, MERGER and SELL transactions."""

    mask = df["type"].str.upper().isin(["BUY", "MERGER", "SELL"])
    df = df.loc[mask].copy()

    df = df[
        ~(
            (df["type"].str.upper() == "MERGER")
            & (df["shares"].isna())
        )
    ].copy()

    return df.loc[mask].copy()


def get_transactions(file, assets):
    """
    Load CSV and return BUY/SELL transactions
    for all symbols belonging to the same position.
    """

    df = load_transactions(file)

    df = filter_asset(df, assets)

    df = filter_buys_and_sells(df)

    return df


def find_first_remaining_buy(df):
    """
    Find the first BUY transaction that still contains shares
    after accounting for all SELL transactions.
    """

    total_sold = abs(
        df.loc[df["type"] == "SELL", "shares"].sum()
    )

    for index, row in df.iterrows():

        if row["type"] != "MERGER" and row["type"] != "BUY":
            continue

        if total_sold >= row["shares"]:
            total_sold -= row["shares"]

        else:
            remaining_shares = row["shares"] - total_sold

            fraction_remaining = (
                remaining_shares / row["shares"]
            )

            fraction_sold = (
                total_sold / row["shares"]
            )

            return (
                index,
                remaining_shares,
                fraction_remaining,
                fraction_sold
            )

    return None, 0.0, 0.0, 0.0


def get_remaining_buys(df):
    """
    Return all BUY transactions that correspond
    to shares currently remaining in the position.
    """

    (
        first_index,
        remaining_shares,
        fraction_remaining,
        fraction_sold
    ) = find_first_remaining_buy(df)

    if first_index is None:
        return pd.DataFrame(
            columns=["shares", "price"]
        )

    remaining_buys = df.loc[
        (df.index >= first_index)
        & (
            (df["type"] == "BUY")
            | (df["type"] == "MERGER")
        )
    ].copy()

    remaining_buys.loc[
        first_index,
        "shares"
    ] = remaining_shares

    return remaining_buys[["shares", "price"]]


def calculate_position_cost(remaining_buys):
    """Calculate total shares and acquisition cost."""

    total_shares = remaining_buys["shares"].sum()

    total_cost = (
        remaining_buys["shares"] *
        remaining_buys["price"]
    ).sum()

    if total_shares == 0:
        return 0.0, 0.0, 0.0

    average_price = total_cost / total_shares

    return total_shares, total_cost, average_price


def calculate_sale_gain(
    remaining_buys,
    shares_to_sell,
    current_price
):
    """
    Calculate the acquisition cost and gain for selling
    a given number of shares using FIFO.
    """

    shares_left = shares_to_sell
    acquisition_cost = 0.0

    for _, row in remaining_buys.iterrows():

        if shares_left <= 0:
            break

        shares_from_lot = min(
            shares_left,
            row["shares"]
        )

        acquisition_cost += (
            shares_from_lot *
            row["price"]
        )

        shares_left -= shares_from_lot

    if shares_left > 1e-9:
        raise ValueError(
            "Cannot sell more shares than are currently held."
        )

    sale_value = shares_to_sell * current_price

    gain = sale_value - acquisition_cost

    return sale_value, acquisition_cost, gain


def calculate_shares_to_sell_for_freistellungsauftrag(
    remaining_buys,
    current_price,
    freistellungsauftrag,
    teilfreistellung=0.30
):
    """
    Calculate how many shares need to be sold to use
    the given Freistellungsauftrag without exceeding it.

    FIFO is used for the acquisition costs.
    """

    if freistellungsauftrag <= 0:
        return 0.0, 0.0, 0.0

    # Benötigter Gewinn vor Teilfreistellung
    required_gain = (
        freistellungsauftrag
        / (1 - teilfreistellung)
    )

    remaining_gain = required_gain
    shares_to_sell = 0.0
    acquisition_cost = 0.0

    for _, row in remaining_buys.iterrows():

        if remaining_gain <= 0:
            break

        lot_shares = row["shares"]
        lot_price = row["price"]

        gain_per_share = current_price - lot_price

        # Dieses Lot erzeugt keinen positiven Gewinn
        if gain_per_share <= 0:

            shares_to_sell += lot_shares

            acquisition_cost += (
                lot_shares * lot_price
            )

            remaining_gain -= (
                lot_shares * gain_per_share
            )

            continue

        # Wie viele Anteile aus diesem Lot werden benötigt?
        shares_from_lot = min(
            lot_shares,
            remaining_gain / gain_per_share
        )

        shares_to_sell += shares_from_lot

        acquisition_cost += (
            shares_from_lot * lot_price
        )

        gain_from_lot = (
            shares_from_lot * gain_per_share
        )

        remaining_gain -= gain_from_lot

    sale_value = shares_to_sell * current_price

    realized_gain = (
        sale_value - acquisition_cost
    )

    taxable_gain = (
        realized_gain * (1 - teilfreistellung)
    )

    return (
        shares_to_sell,
        realized_gain,
        taxable_gain
    )


# ============================================================
# STREAMLIT GUI
# ============================================================

st.set_page_config(
    page_title="ETF Steuerrechner",
    layout="wide"
)

st.title("ETF Steuerrechner")

st.write(
    "FIFO-Berechnung der verbleibenden ETF-Anteile "
    "und des zur Nutzung des Freistellungsauftrags "
    "erforderlichen Verkaufs."
)


# ------------------------------------------------------------
# INPUT
# ------------------------------------------------------------

st.header("Eingaben")

csv_file = st.file_uploader(
    "Trade Republic Transaktions-CSV",
    type=["csv"]
)

col1, col2 = st.columns(2)

with col1:
    current_price = st.number_input(
        "Aktueller Kurs (€)",
        min_value=0.0,
        value=172.74,
        step=0.01
    )

with col2:
    freistellungsauftrag = st.number_input(
        "Verbleibender Freistellungsauftrag (€)",
        min_value=0.0,
        value=754.79,
        step=0.01
    )

asset = st.text_input(
    "ISIN",
    value="IE00BK5BQT80"
)


# ------------------------------------------------------------
# CALCULATION
# ------------------------------------------------------------

if csv_file is not None:

    transactions = get_transactions(
        csv_file,
        [asset]
    )

    st.header("Transaktionen")

    st.dataframe(
        transactions,
        use_container_width=True
    )

    if transactions.empty:

        st.warning(
            f"Keine Transaktionen für {asset} gefunden."
        )

    else:

        (
            index,
            remaining_shares,
            fraction_remaining,
            fraction_sold
        ) = find_first_remaining_buy(
            transactions
        )

        remaining_buys = get_remaining_buys(
            transactions
        )

        (
            total_shares,
            total_cost,
            average_price
        ) = calculate_position_cost(
            remaining_buys
        )


        # ----------------------------------------------------
        # POSITION
        # ----------------------------------------------------

        st.header("Aktuelle Position")

        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric(
                "Anteile",
                f"{total_shares:.6f}"
            )

        with col2:
            st.metric(
                "Anschaffungskosten",
                f"{total_cost:.2f} €"
            )

        with col3:
            st.metric(
                "Ø Kaufpreis",
                f"{average_price:.4f} €"
            )


        # ----------------------------------------------------
        # CURRENT GAIN
        # ----------------------------------------------------

        (
            sale_value,
            acquisition_cost,
            gain
        ) = calculate_sale_gain(
            remaining_buys,
            total_shares,
            current_price
        )

        st.header("Gesamter aktueller Gewinn")

        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric(
                "Verkaufswert",
                f"{sale_value:.2f} €"
            )

        with col2:
            st.metric(
                "Anschaffungskosten",
                f"{acquisition_cost:.2f} €"
            )

        with col3:
            st.metric(
                "Gewinn",
                f"{gain:.2f} €"
            )


        # ----------------------------------------------------
        # FREISTELLUNGSAUFTRAG
        # ----------------------------------------------------

        (
            shares_to_sell,
            realized_gain,
            taxable_gain
        ) = calculate_shares_to_sell_for_freistellungsauftrag(
            remaining_buys,
            current_price,
            freistellungsauftrag
        )

        st.header("Freistellungsauftrag")

        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric(
                "Anteile zu verkaufen",
                f"{shares_to_sell:.6f}"
            )

        with col2:
            st.metric(
                "Verkaufswert",
                f"{shares_to_sell * current_price:.2f} €"
            )

        with col3:
            st.metric(
                "Steuerlicher Gewinn",
                f"{taxable_gain:.2f} €"
            )


        st.write(
            f"Realisierter Gewinn: "
            f"**{realized_gain:.2f} €**"
        )


        # ----------------------------------------------------
        # REMAINING PURCHASES
        # ----------------------------------------------------

        with st.expander("Verbleibende Kauf-Lots"):

            st.dataframe(
                remaining_buys,
                use_container_width=True
            )