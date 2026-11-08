"""African country reference list (ISO 3166-1 codes + UN geoscheme region).

ISO codes and country names are public standard facts. Region follows the
UN geoscheme subregion groupings. Countries are seeded with
``status=placeholder`` — this encodes "Africa-wide by architecture,
evidence-led by coverage": every African country is structurally supported
from day one, while data onboarding proceeds country by country.
"""

# fmt: off
AFRICAN_COUNTRIES = [
    # North Africa
    ("DZ", "DZA", "Algeria", "Northern Africa"),
    ("EG", "EGY", "Egypt", "Northern Africa"),
    ("LY", "LBY", "Libya", "Northern Africa"),
    ("MA", "MAR", "Morocco", "Northern Africa"),
    ("SD", "SDN", "Sudan", "Northern Africa"),
    ("TN", "TUN", "Tunisia", "Northern Africa"),
    ("EH", "ESH", "Western Sahara", "Northern Africa"),
    # West Africa
    ("BJ", "BEN", "Benin", "Western Africa"),
    ("BF", "BFA", "Burkina Faso", "Western Africa"),
    ("CV", "CPV", "Cabo Verde", "Western Africa"),
    ("CI", "CIV", "Côte d'Ivoire", "Western Africa"),
    ("GM", "GMB", "Gambia", "Western Africa"),
    ("GH", "GHA", "Ghana", "Western Africa"),
    ("GN", "GIN", "Guinea", "Western Africa"),
    ("GW", "GNB", "Guinea-Bissau", "Western Africa"),
    ("LR", "LBR", "Liberia", "Western Africa"),
    ("ML", "MLI", "Mali", "Western Africa"),
    ("MR", "MRT", "Mauritania", "Western Africa"),
    ("NE", "NER", "Niger", "Western Africa"),
    ("NG", "NGA", "Nigeria", "Western Africa"),
    ("SN", "SEN", "Senegal", "Western Africa"),
    ("SL", "SLE", "Sierra Leone", "Western Africa"),
    ("TG", "TGO", "Togo", "Western Africa"),
    ("SH", "SHN", "Saint Helena", "Western Africa"),
    # Middle Africa
    ("AO", "AGO", "Angola", "Middle Africa"),
    ("CM", "CMR", "Cameroon", "Middle Africa"),
    ("CF", "CAF", "Central African Republic", "Middle Africa"),
    ("TD", "TCD", "Chad", "Middle Africa"),
    ("CG", "COG", "Congo", "Middle Africa"),
    ("CD", "COD", "Democratic Republic of the Congo", "Middle Africa"),
    ("GQ", "GNQ", "Equatorial Guinea", "Middle Africa"),
    ("GA", "GAB", "Gabon", "Middle Africa"),
    ("ST", "STP", "Sao Tome and Principe", "Middle Africa"),
    # Eastern Africa
    ("BI", "BDI", "Burundi", "Eastern Africa"),
    ("KM", "COM", "Comoros", "Eastern Africa"),
    ("DJ", "DJI", "Djibouti", "Eastern Africa"),
    ("ER", "ERI", "Eritrea", "Eastern Africa"),
    ("ET", "ETH", "Ethiopia", "Eastern Africa"),
    ("KE", "KEN", "Kenya", "Eastern Africa"),
    ("MG", "MDG", "Madagascar", "Eastern Africa"),
    ("MW", "MWI", "Malawi", "Eastern Africa"),
    ("MU", "MUS", "Mauritius", "Eastern Africa"),
    ("MZ", "MOZ", "Mozambique", "Eastern Africa"),
    ("RW", "RWA", "Rwanda", "Eastern Africa"),
    ("SC", "SYC", "Seychelles", "Eastern Africa"),
    ("SO", "SOM", "Somalia", "Eastern Africa"),
    ("SS", "SSD", "South Sudan", "Eastern Africa"),
    ("TZ", "TZA", "United Republic of Tanzania", "Eastern Africa"),
    ("UG", "UGA", "Uganda", "Eastern Africa"),
    ("ZM", "ZMB", "Zambia", "Eastern Africa"),
    ("ZW", "ZWE", "Zimbabwe", "Eastern Africa"),
    ("RE", "REU", "Réunion", "Eastern Africa"),
    ("YT", "MYT", "Mayotte", "Eastern Africa"),
    # Southern Africa
    ("BW", "BWA", "Botswana", "Southern Africa"),
    ("LS", "LSO", "Lesotho", "Southern Africa"),
    ("NA", "NAM", "Namibia", "Southern Africa"),
    ("ZA", "ZAF", "South Africa", "Southern Africa"),
    ("SZ", "SWZ", "Eswatini", "Southern Africa"),
]
# fmt: on
