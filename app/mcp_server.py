import sys
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Travel Concierge MCP Server")

@mcp.tool()
def get_destination_weather(destination: str, dates: str) -> str:
    """Gets the weather forecast for a given destination and date range.
    
    Args:
        destination: The target city or country (e.g., Tokyo, Paris).
        dates: The travel date range (e.g., July 10-15).
    """
    dest = destination.lower()
    if "tokyo" in dest:
        return f"Weather for Tokyo during {dates}: Mild and sunny, average 22°C. No rain expected."
    elif "paris" in dest:
        return f"Weather for Paris during {dates}: Light showers, average 18°C. Carry an umbrella."
    else:
        return f"Weather for {destination} during {dates}: Pleasant, average 25°C with clear skies."

@mcp.tool()
def search_flights_hotels(destination: str, budget: float) -> str:
    """Compares and finds flight and hotel options matching the destination and budget.
    
    Args:
        destination: The travel destination city.
        budget: The total budget in USD for flights and hotels.
    """
    if budget < 500:
        return f"No suitable options found in {destination} for budget ${budget}. Consider increasing budget."
    
    flight_cost = int(budget * 0.4)
    hotel_cost = int(budget * 0.4)
    remaining = int(budget - flight_cost - hotel_cost)
    
    return (
        f"Travel Options for {destination} (Budget: ${budget}):\n"
        f"- Flights: Economy class with local carrier - ${flight_cost}\n"
        f"- Hotel: 3-Star cozy boutique hotel - ${hotel_cost} total\n"
        f"- Remaining Allowance: ${remaining} for local transport/food."
    )

@mcp.tool()
def check_visa_requirements(destination: str, passport_country: str = "India") -> str:
    """Checks visa requirements and compiles a document checklist based on passport country.
    
    Args:
        destination: The destination country.
        passport_country: The passport/citizenship country of the traveler.
    """
    dest = destination.lower()
    pass_cnt = passport_country.lower()
    
    if "japan" in dest or "tokyo" in dest:
        if "india" in pass_cnt:
            return (
                "Visa Requirements for Japan (Indian Passport):\n"
                "- Visa Type: Tourist Visa (Single Entry)\n"
                "- Cost: ~700 INR\n"
                "- Documents required:\n"
                "  1. Valid Passport (with at least 6 months validity)\n"
                "  2. Completed Visa Application Form with photo\n"
                "  3. Flight Itinerary and Hotel Bookings\n"
                "  4. Bank statements for the last 3 months (showing sufficient funds)"
            )
        else:
            return f"Visa not required or Visa on Arrival available for {passport_country} citizens visiting Japan."
            
    elif "france" in dest or "paris" in dest or "europe" in dest:
        return (
            f"Visa Requirements for France/Schengen Area ({passport_country} Passport):\n"
            "- Visa Type: Schengen Tourist Visa (Short stay)\n"
            "- Documents required:\n"
            "  1. Passport valid for 3+ months after departure\n"
            "  2. Schengen Visa Application Form\n"
            "  3. 2 passport-sized photos\n"
            "  4. Travel Insurance (minimum coverage 30,000 EUR)\n"
            "  5. Proof of financial means (bank statements)"
        )
    else:
        return f"Visa on Arrival or E-Visa available for {passport_country} citizens visiting {destination}. Valid passport and return flight ticket required."

if __name__ == "__main__":
    mcp.run()
