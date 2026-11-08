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
    ("DZ", "DZA", "Algeria", "Northern Africa", 2.6, 28.0),
    ("EG", "EGY", "Egypt", "Northern Africa", 30.8, 26.6),
    ("LY", "LBY", "Libya", "Northern Africa", 17.2, 27.0),
    ("MA", "MAR", "Morocco", "Northern Africa", -6.8, 31.9),
    ("SD", "SDN", "Sudan", "Northern Africa", 30.0, 15.6),
    ("TN", "TUN", "Tunisia", "Northern Africa", 9.6, 34.1),
    ("EH", "ESH", "Western Sahara", "Northern Africa", -13.2, 24.2),
    # West Africa
    ("BJ", "BEN", "Benin", "Western Africa", 2.3, 9.6),
    ("BF", "BFA", "Burkina Faso", "Western Africa", -1.6, 12.3),
    ("CV", "CPV", "Cabo Verde", "Western Africa", -23.6, 16.0),
    ("CI", "CIV", "Côte d'Ivoire", "Western Africa", -5.6, 7.5),
    ("GM", "GMB", "Gambia", "Western Africa", -15.4, 13.4),
    ("GH", "GHA", "Ghana", "Western Africa", -1.2, 7.9),
    ("GN", "GIN", "Guinea", "Western Africa", -10.9, 10.4),
    ("GW", "GNB", "Guinea-Bissau", "Western Africa", -15.2, 12.0),
    ("LR", "LBR", "Liberia", "Western Africa", -9.4, 6.5),
    ("ML", "MLI", "Mali", "Western Africa", -3.5, 17.4),
    ("MR", "MRT", "Mauritania", "Western Africa", -10.3, 20.3),
    ("NE", "NER", "Niger", "Western Africa", 9.4, 17.4),
    ("NG", "NGA", "Nigeria", "Western Africa", 8.1, 9.6),
    ("SN", "SEN", "Senegal", "Western Africa", -14.5, 14.4),
    ("SL", "SLE", "Sierra Leone", "Western Africa", -11.8, 8.6),
    ("TG", "TGO", "Togo", "Western Africa", 1.0, 8.5),
    ("SH", "SHN", "Saint Helena", "Western Africa", -5.7, -15.9),
    # Middle Africa
    ("AO", "AGO", "Angola", "Middle Africa", 17.5, -12.3),
    ("CM", "CMR", "Cameroon", "Middle Africa", 12.7, 5.7),
    ("CF", "CAF", "Central African Republic", "Middle Africa", 20.9, 6.6),
    ("TD", "TCD", "Chad", "Middle Africa", 18.7, 15.4),
    ("CG", "COG", "Congo", "Middle Africa", 15.2, -0.8),
    ("CD", "COD", "Democratic Republic of the Congo", "Middle Africa", 23.6, -2.9),
    ("GQ", "GNQ", "Equatorial Guinea", "Middle Africa", 10.3, 1.6),
    ("GA", "GAB", "Gabon", "Middle Africa", 11.8, -0.6),
    ("ST", "STP", "Sao Tome and Principe", "Middle Africa", 6.6, 0.2),
    # Eastern Africa
    ("BI", "BDI", "Burundi", "Eastern Africa", 29.9, -3.4),
    ("KM", "COM", "Comoros", "Eastern Africa", 43.4, -11.7),
    ("DJ", "DJI", "Djibouti", "Eastern Africa", 42.6, 11.7),
    ("ER", "ERI", "Eritrea", "Eastern Africa", 38.8, 15.2),
    ("ET", "ETH", "Ethiopia", "Eastern Africa", 39.6, 8.6),
    ("KE", "KEN", "Kenya", "Eastern Africa", 37.9, 0.2),
    ("MG", "MDG", "Madagascar", "Eastern Africa", 46.7, -19.0),
    ("MW", "MWI", "Malawi", "Eastern Africa", 34.3, -13.2),
    ("MU", "MUS", "Mauritius", "Eastern Africa", 57.6, -20.3),
    ("MZ", "MOZ", "Mozambique", "Eastern Africa", 35.5, -17.3),
    ("RW", "RWA", "Rwanda", "Eastern Africa", 29.9, -2.0),
    ("SC", "SYC", "Seychelles", "Eastern Africa", 55.5, -4.7),
    ("SO", "SOM", "Somalia", "Eastern Africa", 45.9, 6.0),
    ("SS", "SSD", "South Sudan", "Eastern Africa", 31.3, 7.3),
    ("TZ", "TZA", "United Republic of Tanzania", "Eastern Africa", 34.9, -6.4),
    ("UG", "UGA", "Uganda", "Eastern Africa", 32.4, 1.3),
    ("ZM", "ZMB", "Zambia", "Eastern Africa", 27.8, -13.5),
    ("ZW", "ZWE", "Zimbabwe", "Eastern Africa", 29.9, -19.0),
    ("RE", "REU", "Réunion", "Eastern Africa", 55.5, -21.1),
    ("YT", "MYT", "Mayotte", "Eastern Africa", 45.2, -12.8),
    # Southern Africa
    ("BW", "BWA", "Botswana", "Southern Africa", 24.7, -22.3),
    ("LS", "LSO", "Lesotho", "Southern Africa", 28.2, -29.6),
    ("NA", "NAM", "Namibia", "Southern Africa", 17.2, -22.1),
    ("ZA", "ZAF", "South Africa", "Southern Africa", 24.7, -29.0),
    ("SZ", "SWZ", "Eswatini", "Southern Africa", 31.5, -26.5),
]
# fmt: on

centroids = {c[1]: (c[4], c[5]) for c in AFRICAN_COUNTRIES}
