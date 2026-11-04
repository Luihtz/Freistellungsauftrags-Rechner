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
    teilfreistellung
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



def calculate_portfolio_rebalancing(
    etf_daten,
    csv_file,
    freistellungsauftrag,
    teilfreistellung
):
    """
    tax optimized portfolio-rebalancing.

    1. necessary sells.
    2. additional sells to use the FSA.
    3. buy-orders for rebalancing.
    """

    positionen = []
    verwendete_isins = set()

    # calculate current position

    for etf in etf_daten:

        isin = str(etf["ISIN"]).strip()
        kurs = float(etf["Kurs"])
        zielgewicht = float(etf["Zielgewicht"])

        if not isin:
            continue

        if isin in verwendete_isins:
            raise ValueError(
                f"Die ISIN {isin} wurde mehrfach eingegeben."
            )

        verwendete_isins.add(isin)

        if kurs <= 0:
            raise ValueError(f"Ungültiger Kurs für {isin}")

        csv_file.seek(0)

        transactions = get_transactions(
            csv_file,
            [isin]
        )

        if transactions.empty:

            remaining_buys = pd.DataFrame(
                columns=["shares", "price"]
            )

            anzahl_anteile = 0.0

        else:

            remaining_buys = get_remaining_buys(
                transactions
            )

            if remaining_buys.empty:
                anzahl_anteile = 0.0

            else:

                (
                    anzahl_anteile,
                    _,
                    _
                ) = calculate_position_cost(
                    remaining_buys
                )

        aktueller_wert = anzahl_anteile * kurs

        positionen.append({
            "ISIN": isin,
            "Kurs": kurs,
            "Anteile": anzahl_anteile,
            "Aktueller Wert": aktueller_wert,
            "Zielgewicht": zielgewicht,
            "Remaining Buys": remaining_buys
        })

    if not positionen:
        raise ValueError("Keine gültigen ETFs vorhanden.")

    portfolio = pd.DataFrame(positionen)

    # portofolio and target value

    portfolio_wert = portfolio["Aktueller Wert"].sum()

    zielgewicht_summe = portfolio["Zielgewicht"].sum()

    if zielgewicht_summe <= 0:
        raise ValueError("Ungültige Zielgewichtung.")

    if not 0 <= teilfreistellung <= 1:
        raise ValueError("Ungültige Teilfreistellung.")

    portfolio["Zielgewicht normiert"] = (
        portfolio["Zielgewicht"] / zielgewicht_summe
    )

    portfolio["Aktuelles Gewicht"] = (
        portfolio["Aktueller Wert"] / portfolio_wert * 100
        if portfolio_wert > 0
        else 0.0
    )

    portfolio["Zielwert"] = (
        portfolio["Zielgewicht normiert"] * portfolio_wert
    )

    portfolio["Differenz"] = (
        portfolio["Zielwert"] - portfolio["Aktueller Wert"]
    )

    portfolio["Zielanteile"] = (
        portfolio["Zielwert"] / portfolio["Kurs"]
    )

    # sell order

    anzahl = len(portfolio)

    verkaufte_anteile = [0.0] * anzahl
    fsa_nutzung = [0.0] * anzahl

    fsa_rest = max(0.0, float(freistellungsauftrag))

    def berechne_verkauf(index, anteile):

        if anteile <= 0:
            return 0.0, 0.0, 0.0

        row = portfolio.iloc[index]

        return calculate_sale_gain(
            row["Remaining Buys"],
            anteile,
            row["Kurs"]
        )

    def steuerlicher_gewinn(index, anteile):

        if anteile <= 0:
            return 0.0

        _, _, gewinn = berechne_verkauf(
            index,
            anteile
        )

        return max(
            0.0,
            gewinn * (1 - teilfreistellung)
        )

    # necessary sells

    for i, row in portfolio.iterrows():

        aktuelle_anteile = row["Anteile"]
        ziel_anteile = row["Zielanteile"]

        # sell overweighted etfs
        notwendiger_verkauf = max(
            0.0,
            aktuelle_anteile - ziel_anteile
        )

        if notwendiger_verkauf <= 0:
            continue

        verkaufte_anteile[i] = notwendiger_verkauf

        taxable = steuerlicher_gewinn(
            i,
            notwendiger_verkauf
        )

        genutzt = min(
            fsa_rest,
            taxable
        )

        fsa_nutzung[i] += genutzt
        fsa_rest -= genutzt

    # additional sells for FSA

    # Übergewichtete ETFs zuerst berücksichtigen.
    # Danach weitere ETFs mit positiven Gewinnen.

    verkaufsreihenfolge = sorted(
        range(anzahl),
        key=lambda i: (
            portfolio.iloc[i]["Differenz"] >= 0,
            -(
                steuerlicher_gewinn(
                    i,
                    portfolio.iloc[i]["Anteile"]
                ) /
                max(
                    portfolio.iloc[i]["Aktueller Wert"],
                    0.01
                )
            )
        )
    )

    for i in verkaufsreihenfolge:

        if fsa_rest <= 0.01:
            break

        row = portfolio.iloc[i]

        noch_verfuegbar = (
            row["Anteile"] - verkaufte_anteile[i]
        )

        if noch_verfuegbar <= 0:
            continue

        bereits_steuerlich = steuerlicher_gewinn(
            i,
            verkaufte_anteile[i]
        )

        voll_steuerlich = steuerlicher_gewinn(
            i,
            row["Anteile"]
        )

        zusaetzlicher_gewinn = max(
            0.0,
            voll_steuerlich - bereits_steuerlich
        )

        if zusaetzlicher_gewinn <= 0.01:
            continue

        # rest-sell possible?
        if zusaetzlicher_gewinn <= fsa_rest:

            extra_verkauf = noch_verfuegbar

        else:

            # binary search for max sell for FSA

            low = 0.0
            high = noch_verfuegbar

            for _ in range(60):

                mitte = (low + high) / 2

                gesamter_verkauf = (
                    verkaufte_anteile[i] + mitte
                )

                neuer_gewinn = steuerlicher_gewinn(
                    i,
                    gesamter_verkauf
                )

                differenz_gewinn = max(
                    0.0,
                    neuer_gewinn - bereits_steuerlich
                )

                if differenz_gewinn <= fsa_rest:
                    low = mitte
                else:
                    high = mitte

            extra_verkauf = low

        if extra_verkauf <= 0:
            continue

        verkaufte_anteile[i] += extra_verkauf

        neuer_steuerlicher_gewinn = steuerlicher_gewinn(
            i,
            verkaufte_anteile[i]
        )

        zusätzlicher_fsa_bedarf = max(
            0.0,
            neuer_steuerlicher_gewinn - bereits_steuerlich
        )

        genutzt = min(
            fsa_rest,
            zusätzlicher_fsa_bedarf
        )

        fsa_nutzung[i] += genutzt
        fsa_rest -= genutzt

    # calculate buys

    ergebnisse = []

    for i, row in portfolio.iterrows():

        kurs = row["Kurs"]

        aktuelle_anteile = row["Anteile"]

        ziel_anteile = row["Zielanteile"]

        shares_to_sell = verkaufte_anteile[i]

        verbleibende_anteile = (
            aktuelle_anteile - shares_to_sell
        )

        shares_to_buy = max(
            0.0,
            ziel_anteile - verbleibende_anteile
        )

        (
            sale_value,
            acquisition_cost,
            realized_gain
        ) = berechne_verkauf(
            i,
            shares_to_sell
        )

        taxable_gain = realized_gain * (
            1 - teilfreistellung
        )

        if shares_to_sell > 0 and shares_to_buy > 0:
            handlung = "Verkaufen und Kaufen"

        elif shares_to_sell > 0:
            handlung = "Verkaufen"

        elif shares_to_buy > 0:
            handlung = "Kaufen"

        else:
            handlung = "Keine Änderung"

        ergebnisse.append({

            "ISIN": row["ISIN"],

            "Aktueller Wert": row["Aktueller Wert"],

            "Aktuelles Gewicht (%)": row["Aktuelles Gewicht"],

            "Zielgewicht (%)": (
                row["Zielgewicht normiert"] * 100
            ),

            "Zielwert": row["Zielwert"],

            "Handlung": handlung,

            "Anteile verkaufen": shares_to_sell,

            "Anteile kaufen": shares_to_buy,

            "Verkaufswert": sale_value,

            "Anschaffungskosten": acquisition_cost,

            "Realisierter Gewinn": realized_gain,

            "Steuerlicher Gewinn": taxable_gain,

            "Freistellungsauftrag genutzt": fsa_nutzung[i]

        })

    ergebnis_df = pd.DataFrame(ergebnisse)

    kaufvolumen = (
        ergebnis_df["Anteile kaufen"] *
        portfolio["Kurs"].reset_index(drop=True)
    ).sum()

    verkaufsvolumen = ergebnis_df["Verkaufswert"].sum()

    realisierter_gewinn = (
        ergebnis_df["Realisierter Gewinn"].sum()
    )

    steuerlicher_gewinn = (
        ergebnis_df["Steuerlicher Gewinn"]
        .clip(lower=0)
        .sum()
    )

    fsa_genutzt = (
        ergebnis_df["Freistellungsauftrag genutzt"].sum()
    )

    return (
        ergebnis_df,
        portfolio_wert,
        kaufvolumen,
        verkaufsvolumen,
        realisierter_gewinn,
        steuerlicher_gewinn,
        fsa_genutzt,
        fsa_rest
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

# Teilfreistellung

moegliche_teilfreistellungen = {
    "Aktienfonds ≥ 51%": 0.3,
    "Mischfonds (Aktienquote ≥ 25%)": 0.15,
    "Sonstige (Aktienquote < 25%)": 0.0
}

teilfreistellung = st.selectbox(
    "Teilfreistellung:",
    options=list(moegliche_teilfreistellungen.keys()),
    index = 0
)

teilfreistellung_wert = moegliche_teilfreistellungen[teilfreistellung]

# Rebalancing
st.divider()

rebalancing = st.checkbox("Rebalancing durchführen")

etf_daten = []

if rebalancing:

    st.subheader("Rebalancing-Einstellungen")

    anzahl_etfs = st.number_input(
        "Wie viele ETFs stehen zur Verfügung?",
        min_value=1,
        max_value=20,
        value=2,
        step=1
    )

    st.write("**ETF-Daten:**")

    ETF_DEFAULTS = [
        {
            "ISIN": "IE0009DRDY20",
            "Zielgewicht": 70.0,
            "Kurs": 40.660
        },
        {
            "ISIN": "LU2300295123",
            "Zielgewicht": 30.0,
            "Kurs": 24.270
        }
    ]

    for i in range(int(anzahl_etfs)):

        defaults = (
            ETF_DEFAULTS[i]
            if i < len(ETF_DEFAULTS)
            else {}
        )

        st.markdown(
            f"**ETF {i+1}**"
        )

        col1, col2, col3 = st.columns(3)

        with col1:

            isin = st.text_input(
                "ISIN",
                value=defaults.get("ISIN", ""),
                key=f"isin_{i}"
            )

        with col2:
            kurs = st.number_input(
                "Aktueller Wert (€) / Kurs pro Anteil (€)",
                min_value=0.0,
                value=defaults.get("Kurs", 0.0),
                step=100.0,
                key=f"wert_{i}"
            )

        with col3:
            zielgewicht = st.number_input(
                "Zielgewicht (%)",
                min_value=0.0,
                max_value=100.0,
                value=defaults.get("Zielgewicht", 0.0),
                step=1.0,
                key=f"gewicht_{i}"
            )

        etf_daten.append({
            "ISIN": isin,
            "Kurs": kurs,
            "Zielgewicht": zielgewicht
        })

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
            freistellungsauftrag,
            teilfreistellung_wert
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


# ------------------------------------------------------------
# REBALANCING
# ------------------------------------------------------------

if rebalancing:

    st.header("Rebalancing")

    try:

        (
            portfolio,
            portfolio_wert,
            kaufvolumen,
            verkaufsvolumen,
            realisierter_gewinn,
            steuerlicher_gewinn,
            fsa_genutzt,
            fsa_rest
        ) = calculate_portfolio_rebalancing(
            etf_daten,
            csv_file,
            freistellungsauftrag,
            teilfreistellung_wert
        )

        # ----------------------------------------------------
        # PORTFOLIO
        # ----------------------------------------------------

        st.subheader("Aktuelles Portfolio")

        col1, col2 = st.columns(2)

        with col1:
            st.metric(
                "Gesamtwert",
                f"{portfolio_wert:.2f} €"
            )

        with col2:
            st.metric(
                "Anzahl ETFs",
                len(portfolio)
            )

        # ----------------------------------------------------
        # ALLOCATION
        # ----------------------------------------------------

        st.subheader("Portfolio-Allokation")

        st.dataframe(
            portfolio[
                [
                    "ISIN",
                    "Aktueller Wert",
                    "Aktuelles Gewicht (%)",
                    "Zielgewicht (%)",
                    "Zielwert"
                ]
            ],
            use_container_width=True
        )

        # ----------------------------------------------------
        # TRADING
        # ----------------------------------------------------

        st.subheader("Rebalancing-Empfehlung")

        st.dataframe(
            portfolio[
                [
                    "ISIN",
                    "Handlung",
                    "Anteile verkaufen",
                    "Anteile kaufen",
                    "Verkaufswert"
                ]
            ],
            use_container_width=True
        )

        # ----------------------------------------------------
        # TAX
        # ----------------------------------------------------

        st.subheader("Steuerliche Auswirkungen")

        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric(
                "Realisierter Gewinn",
                f"{realisierter_gewinn:.2f} €"
            )

        with col2:
            st.metric(
                "Steuerlicher Gewinn",
                f"{steuerlicher_gewinn:.2f} €"
            )

        with col3:
            st.metric(
                "Verkaufsvolumen",
                f"{verkaufsvolumen:.2f} €"
            )

        col1, col2, col3 = st.columns(3)

        cols = st.columns(len(portfolio)+2)

        for i, (_, row) in enumerate(portfolio.iterrows()):
            with cols[i]:
                st.metric(
                    label=f"Gewicht ETF {i+1}",
                    value=f"{row['Zielgewicht (%)']:.2f} %"
                )

        with cols[-2]:
            st.metric(
                "Freistellungsauftrag genutzt",
                f"{fsa_genutzt:.2f} €"
            )

        with cols[-1]:
            st.metric(
                "Verbleibender Freistellungsauftrag",
                f"{fsa_rest:.2f} €"
            )

    except ValueError as e:

        st.warning(str(e))
