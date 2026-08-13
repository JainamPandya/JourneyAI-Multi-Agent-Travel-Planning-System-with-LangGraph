import os
import re
import certifi
import airportsdata
import pycountry
import requests
from dotenv import load_dotenv

load_dotenv()

os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

API_KEY = os.getenv("AVIATIONSTACK_API_KEY")

BASE_URL = "https://api.aviationstack.com/v1/flights"

# Default origin when only a destination is mentioned
DEFAULT_ORIGIN_IATA = os.getenv("DEFAULT_ORIGIN_IATA", "DEL")

# Load airport database
AIRPORTS = airportsdata.load("IATA")


# ---------------------------------------------------------
# COUNTRY ALIASES
# ---------------------------------------------------------

COUNTRY_ALIASES = {
    "usa": "US",
    "u.s.a": "US",
    "u.s.": "US",
    "america": "US",
    "united states": "US",

    "uk": "GB",
    "u.k.": "GB",
    "britain": "GB",
    "england": "GB",

    "uae": "AE",
    "dubai": "AE",

    "south korea": "KR",
    "korea": "KR",

    "russia": "RU",
    "vietnam": "VN",
    "bangladesh": "BD",
    "india": "IN",
    "japan": "JP",
    "china": "CN",
    "singapore": "SG",
    "malaysia": "MY",
    "thailand": "TH",
    "indonesia": "ID",
    "nepal": "NP",
    "qatar": "QA",
    "saudi arabia": "SA",
    "turkey": "TR",
    "canada": "CA",
    "australia": "AU",
    "germany": "DE",
    "france": "FR",
    "italy": "IT",
    "spain": "ES",
}


# ---------------------------------------------------------
# MAJOR AIRPORTS PER COUNTRY
# ---------------------------------------------------------
# These are the airports we will search instead of using
# only one airport per country.

COUNTRY_AIRPORTS = {
    "IN": ["DEL", "BOM", "BLR", "MAA", "HYD", "CCU"],
    "CN": ["PEK", "PVG", "CAN", "SZX", "CTU", "HKG"],
    "JP": ["NRT", "HND", "KIX", "NGO"],
    "AE": ["DXB", "AUH", "SHJ"],
    "US": ["JFK", "LAX", "SFO", "ORD", "ATL"],
    "GB": ["LHR", "LGW", "MAN", "BHX"],
    "SG": ["SIN"],
    "TH": ["BKK", "DMK", "HKT"],
    "MY": ["KUL", "PEN"],
    "NP": ["KTM"],
    "BD": ["DAC", "CGP"],
    "AU": ["SYD", "MEL", "BNE"],
    "CA": ["YYZ", "YVR", "YUL"],
    "DE": ["FRA", "MUC", "BER"],
    "FR": ["CDG", "ORY"],
    "IT": ["FCO", "MXP"],
    "ES": ["MAD", "BCN"],
    "KR": ["ICN", "GMP"],
    "QA": ["DOH"],
    "SA": ["JED", "RUH"],
    "TR": ["IST", "SAW"],
    "ID": ["CGK", "DPS"],
}


# ---------------------------------------------------------
# TEXT CLEANING
# ---------------------------------------------------------

def clean_text(text: str) -> str:
    text = text.lower().strip()

    text = re.sub(r"[^a-z0-9\s]", " ", text)

    text = re.sub(r"\s+", " ", text)

    stop_words = [
        "flight",
        "flights",
        "ticket",
        "tickets",
        "trip",
        "travel",
        "plan",
        "complete",
        "days",
        "day",
        "including",
        "hotel",
        "hotels",
        "sightseeing",
        "under",
        "budget",
        "info",
        "information",
    ]

    words = [
        word
        for word in text.split()
        if word not in stop_words
    ]

    return " ".join(words).strip()


# ---------------------------------------------------------
# COUNTRY NAME → COUNTRY CODE
# ---------------------------------------------------------

def country_name_to_code(text: str):
    text = clean_text(text)

    if text in COUNTRY_ALIASES:
        return COUNTRY_ALIASES[text]

    try:
        country = pycountry.countries.lookup(text)
        return country.alpha_2
    except LookupError:
        pass

    # Search country name inside longer text
    for country in pycountry.countries:
        country_name = country.name.lower()

        if country_name in text:
            return country.alpha_2

    # Search aliases inside longer text
    for alias, code in COUNTRY_ALIASES.items():
        if alias in text:
            return code

    return None


# ---------------------------------------------------------
# FIND COUNTRIES IN USER QUERY
# ---------------------------------------------------------

def find_country_mentions(query: str):
    q = query.lower()

    countries = []

    # Aliases
    for alias, code in COUNTRY_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", q):
            if code not in [c[1] for c in countries]:
                countries.append((alias, code))

    # Official country names
    for country in pycountry.countries:
        name = country.name.lower()

        if len(name) < 4:
            continue

        if re.search(rf"\b{re.escape(name)}\b", q):
            if country.alpha_2 not in [c[1] for c in countries]:
                countries.append((name, country.alpha_2))

    return countries


# ---------------------------------------------------------
# RESOLVE LOCATION TO IATA
# ---------------------------------------------------------

def resolve_location_to_iata(location: str):

    if not location:
        return None

    raw_location = location.strip()

    # Direct airport code
    if re.fullmatch(r"[A-Za-z]{3}", raw_location):

        code = raw_location.upper()

        if code in AIRPORTS:
            return code

    location_clean = clean_text(raw_location)

    if not location_clean:
        return None

    # Country
    country_code = country_name_to_code(location_clean)

    if country_code:

        airports = COUNTRY_AIRPORTS.get(country_code)

        if airports:
            return airports[0]

    # Search airport database by city
    matches = []

    for iata, airport in AIRPORTS.items():

        city = str(
            airport.get("city", "")
        ).lower().strip()

        name = str(
            airport.get("name", "")
        ).lower().strip()

        score = 0

        if city == location_clean:
            score += 100

        elif location_clean in city:
            score += 70

        if location_clean in name:
            score += 50

        if "international" in name:
            score += 10

        if score > 0:
            matches.append((score, iata))

    if matches:

        matches.sort(reverse=True)

        return matches[0][1]

    return None


# ---------------------------------------------------------
# PARSE ROUTE
# ---------------------------------------------------------

def parse_route(query: str):

    q = query.strip()
    q_lower = q.lower()

    # ---------------------------------------------
    # from X to Y
    # ---------------------------------------------

    match = re.search(
        r"\bfrom\s+(.+?)\s+\bto\s+(.+?)"
        r"(?:\s+(?:on|for|under|including|with|in|at)\b|[.!?]|$)",
        q_lower
    )

    if match:

        origin_text = match.group(1)
        dest_text = match.group(2)

        dep = resolve_location_to_iata(origin_text)
        arr = resolve_location_to_iata(dest_text)

        return dep, arr

    # ---------------------------------------------
    # X trip from Y
    # Example:
    # Nepal trip from India
    # ---------------------------------------------

    match = re.search(
        r"\b(?:\d+\s+)?(.+?)\s+trip\s+from\s+(.+?)(?:[.!?]|$)",
        q_lower
    )

    if match:

        dest_text = match.group(1)
        origin_text = match.group(2)

        dep = resolve_location_to_iata(origin_text)
        arr = resolve_location_to_iata(dest_text)

        return dep, arr

    # ---------------------------------------------
    # to X from Y
    # ---------------------------------------------

    match = re.search(
        r"\bto\s+(.+?)\s+\bfrom\s+(.+?)"
        r"(?:\s+(?:on|for|under|including|with|in|at)\b|[.!?]|$)",
        q_lower
    )

    if match:

        dest_text = match.group(1)
        origin_text = match.group(2)

        dep = resolve_location_to_iata(origin_text)
        arr = resolve_location_to_iata(dest_text)

        return dep, arr

    # ---------------------------------------------
    # Only one country mentioned
    # Use default origin
    # ---------------------------------------------

    countries = find_country_mentions(q)

    if len(countries) == 1:

        destination_code = countries[0][1]

        airports = COUNTRY_AIRPORTS.get(destination_code)

        if airports:
            return DEFAULT_ORIGIN_IATA, airports[0]

    return None, None


# ---------------------------------------------------------
# SEARCH ONE ROUTE
# ---------------------------------------------------------

def search_single_route(
    departure: str,
    arrival: str,
    limit: int = 10
):

    params = {
        "access_key": API_KEY,
        "dep_iata": departure,
        "arr_iata": arrival,
        "limit": min(limit, 100),
    }

    try:

        response = requests.get(
            BASE_URL,
            params=params,
            timeout=30
        )

        data = response.json()

    except requests.exceptions.RequestException as e:

        print(f"API request failed: {e}")

        return []

    except ValueError:

        print("API returned invalid JSON.")

        return []

    if "error" in data:

        print(
            "API error:",
            data["error"].get("message", "Unknown error")
        )

        return []

    return data.get("data", [])


# ---------------------------------------------------------
# FORMAT FLIGHT
# ---------------------------------------------------------

def format_flight(flight: dict):

    airline = (
        flight.get("airline", {}).get("name")
        or "Unknown airline"
    )

    flight_number = (
        flight.get("flight", {}).get("iata")
        or "Unknown flight"
    )

    status = (
        flight.get("flight_status")
        or "Unknown"
    )

    dep = flight.get("departure", {}) or {}
    arr = flight.get("arrival", {}) or {}

    dep_airport = dep.get("airport") or "Unknown"
    dep_iata = dep.get("iata") or "Unknown"
    dep_scheduled = dep.get("scheduled") or "Unknown"

    arr_airport = arr.get("airport") or "Unknown"
    arr_iata = arr.get("iata") or "Unknown"
    arr_scheduled = arr.get("scheduled") or "Unknown"

    return f"""
Airline: {airline}
Flight: {flight_number}
Status: {status}

Departure:
- Airport: {dep_airport}
- IATA: {dep_iata}
- Scheduled: {dep_scheduled}

Arrival:
- Airport: {arr_airport}
- IATA: {arr_iata}
- Scheduled: {arr_scheduled}
""".strip()


# ---------------------------------------------------------
# COUNTRY → COUNTRY SEARCH
# ---------------------------------------------------------

def search_country_to_country(
    origin_country: str,
    destination_country: str,
    limit: int = 10
):

    origin_airports = COUNTRY_AIRPORTS.get(
        origin_country,
        []
    )

    destination_airports = COUNTRY_AIRPORTS.get(
        destination_country,
        []
    )

    if not origin_airports:
        return "No airports configured for origin country."

    if not destination_airports:
        return "No airports configured for destination country."

    print(
        f"\nSearching {origin_country} → {destination_country}"
    )

    all_flights = []

    # Limit combinations to avoid excessive API calls
    max_routes = 10

    route_count = 0

    for departure in origin_airports:

        for arrival in destination_airports:

            if route_count >= max_routes:
                break

            route_count += 1

            print(
                f"Checking route: {departure} → {arrival}"
            )

            flights = search_single_route(
                departure,
                arrival,
                limit=limit
            )

            for flight in flights:

                all_flights.append(flight)

                if len(all_flights) >= limit:
                    break

            if len(all_flights) >= limit:
                break

        if len(all_flights) >= limit:
            break

    if not all_flights:

        return (
            f"No live flight data found between "
            f"{origin_country} and {destination_country}."
        )

    formatted = [
        format_flight(flight)
        for flight in all_flights[:limit]
    ]

    return (
        f"Live flights: "
        f"{origin_country} → {destination_country}\n\n"
        + "\n\n---\n\n".join(formatted)
    )


# ---------------------------------------------------------
# MAIN SEARCH FUNCTION
# ---------------------------------------------------------

def search_flights(query: str, limit: int = 10):

    if not API_KEY:

        return (
            "Flight API error: AVIATIONSTACK_API_KEY "
            "is missing."
        )

    countries = find_country_mentions(query)

    # -------------------------------------------------
    # Country → Country
    # -------------------------------------------------

    if len(countries) >= 2:

        origin_country = countries[0][1]
        destination_country = countries[1][1]

        print(
            "Detected countries:",
            origin_country,
            "→",
            destination_country
        )

        return search_country_to_country(
            origin_country,
            destination_country,
            limit
        )

    # -------------------------------------------------
    # Normal airport/city route
    # -------------------------------------------------

    dep_iata, arr_iata = parse_route(query)

    print("QUERY:", query)
    print("DEP:", dep_iata)
    print("ARR:", arr_iata)

    if not dep_iata and not arr_iata:

        return "Could not determine flight route."

    params = {
        "access_key": API_KEY,
        "limit": min(limit, 100),
    }

    if dep_iata:
        params["dep_iata"] = dep_iata

    if arr_iata:
        params["arr_iata"] = arr_iata

    try:

        response = requests.get(
            BASE_URL,
            params=params,
            timeout=30
        )

        data = response.json()

    except requests.exceptions.RequestException as e:

        return f"Flight API request failed: {e}"

    except ValueError:

        return "Flight API returned invalid JSON."

    if "error" in data:

        error = data["error"]

        return (
            "Flight API error:\n"
            f"Code: {error.get('code', 'Unknown')}\n"
            f"Message: {error.get('message', 'Unknown error')}"
        )

    flight_data = data.get("data", [])

    if not flight_data:

        route_text = ""

        if dep_iata and arr_iata:
            route_text = (
                f" for route {dep_iata} to {arr_iata}"
            )

        elif dep_iata:
            route_text = f" from {dep_iata}"

        elif arr_iata:
            route_text = f" to {arr_iata}"

        return (
            f"No live flight data found{route_text}."
        )

    formatted = [
        format_flight(flight)
        for flight in flight_data[:limit]
    ]

    return "\n\n---\n\n".join(formatted)


# ---------------------------------------------------------
# TEST
# ---------------------------------------------------------

if __name__ == "__main__":

    print(
        search_flights(
            "Plan a 7 days China trip from India"
        )
    )