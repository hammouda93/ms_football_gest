"""Shared presentation-style presets for the Django app and Windows agent."""

DEFAULT_PRESENTATION_STYLE = "stadium_golden_hour"


PRESENTATION_STYLES = (
    {
        "value": "stadium_golden_hour",
        "label": "Stade — Golden Hour",
        "category": "Outdoor",
        "icon": "fa-sun",
        "summary": "Soleil doré, ciel vivant et rendu premium naturel.",
        "image_direction": (
            "Place the player pitch-side in a believable modern football stadium during golden hour. "
            "Use warm low-angle sunlight, restrained lens glow, elegant club-color accents, a clean sky, "
            "a few thin clouds and two or three tiny distant birds. Keep the atmosphere premium, calm and realistic."
        ),
        "motion_direction": (
            "Let the existing warm sunlight glint softly once, move existing thin clouds very slowly, and let "
            "two or three tiny distant birds cross only the high background sky. Keep all movement subtle."
        ),
    },
    {
        "value": "stadium_night",
        "label": "Stade de nuit",
        "category": "Outdoor",
        "icon": "fa-moon",
        "summary": "Projecteurs, légère brume et ambiance grand match.",
        "image_direction": (
            "Place the player pitch-side in a large stadium at night under professional floodlights. Use subtle "
            "atmospheric haze, deep stadium perspective, restrained club colors and a few distant photographic "
            "flash points. No fireworks, crowd chaos or exaggerated effects."
        ),
        "motion_direction": (
            "Animate only a very slow drift in the existing stadium haze, a gentle stable floodlight glow and one "
            "or two tiny distant camera flashes. No strobe, flicker, sweeping spotlights or exposure pumping."
        ),
    },
    {
        "value": "training_ground",
        "label": "Terrain d’entraînement",
        "category": "Outdoor",
        "icon": "fa-futbol",
        "summary": "Lumière du matin et environnement sportif naturel.",
        "image_direction": (
            "Place the player beside a premium professional training pitch in soft morning daylight. Show clean "
            "training-ground depth, subtle greenery and understated club branding, with a light breeze and a calm "
            "working-football atmosphere rather than a match-day spectacle."
        ),
        "motion_direction": (
            "Move only existing distant leaves or grass very lightly in a soft breeze, allow slow natural cloud "
            "motion if sky is visible, and optionally two tiny distant birds. Keep the training ground calm."
        ),
    },
    {
        "value": "modern_stands",
        "label": "Tribunes modernes",
        "category": "Outdoor",
        "icon": "fa-building",
        "summary": "Architecture du stade et identité visuelle du club.",
        "image_direction": (
            "Frame the player near architecturally striking modern stadium stands. Use clean structural lines, "
            "premium depth, controlled daylight and subtle club-color seating or banners. Keep the venue believable, "
            "uncluttered and visually strong without inventing stadium signage."
        ),
        "motion_direction": (
            "Use an almost imperceptible architectural parallax, very slight movement in existing distant banners, "
            "and slow cloud movement only when a real sky area exists. Keep signs and graphics perfectly stable."
        ),
    },
    {
        "value": "player_tunnel",
        "label": "Tunnel des joueurs",
        "category": "Indoor",
        "icon": "fa-person-walking-arrow-right",
        "summary": "Lumière dramatique venant du terrain.",
        "image_direction": (
            "Place the player inside a realistic premium stadium tunnel, facing camera with the pitch entrance glowing "
            "softly behind. Use strong but controlled leading lines, subtle atmospheric depth and restrained club-color "
            "details. No crowd, pyrotechnics or theatrical fantasy."
        ),
        "motion_direction": (
            "Animate a very slow drift in existing tunnel haze and one restrained natural light pulse from the pitch "
            "entrance. Keep walls, signage, crest and all graphic elements locked and perfectly stable."
        ),
    },
    {
        "value": "premium_locker_room",
        "label": "Vestiaire premium",
        "category": "Indoor",
        "icon": "fa-shirt",
        "summary": "Vestiaire moderne, chaleureux et officiel.",
        "image_direction": (
            "Place the player in a refined modern first-team locker room. Use warm practical lighting, clean lockers, "
            "one subtle correctly proportioned club crest and restrained club colors. Avoid duplicate kits, fake names, "
            "fake numbers, clutter and excessive luxury styling."
        ),
        "motion_direction": (
            "Animate only a very subtle practical-light shimmer and tiny realistic movement in existing hanging fabric "
            "or ambient haze. Keep lockers, printed names, numbers, logos and reflections temporally stable."
        ),
    },
    {
        "value": "official_club_studio",
        "label": "Studio officiel du club",
        "category": "Studio",
        "icon": "fa-camera",
        "summary": "Fond graphique propre aux couleurs du club.",
        "image_direction": (
            "Create a professional official club media-day studio. Use a clean graphic backdrop derived only from the "
            "uploaded crest geometry and verified club colors, soft key light, controlled rim light and premium negative "
            "space. Keep the design photographic, minimal and broadcast-ready."
        ),
        "motion_direction": (
            "Use only a slow controlled light sweep across the existing backdrop and an imperceptible depth shift. "
            "The club crest, typography, graphic lines and colors must remain perfectly fixed without morphing."
        ),
    },
    {
        "value": "dark_cinema_studio",
        "label": "Studio cinéma sombre",
        "category": "Studio",
        "icon": "fa-film",
        "summary": "Fond noir et lumière cinéma haut de gamme.",
        "image_direction": (
            "Create a dark cinematic portrait studio with a deep charcoal background, soft sculpted key light and "
            "restrained rim lights in verified club colors. Add only minimal atmospheric depth and one subtle crest "
            "element. Preserve clear separation around the player's silhouette."
        ),
        "motion_direction": (
            "Allow only a very slow drift in existing fine studio haze and one soft restrained rim-light pulse. No "
            "flashing, moving graphics, color cycling, background transformation or exposure pumping."
        ),
    },
    {
        "value": "press_room",
        "label": "Salle de conférence",
        "category": "Indoor",
        "icon": "fa-microphone-lines",
        "summary": "Annonce de transfert sobre et professionnelle.",
        "image_direction": (
            "Place the player in a polished football press or signing presentation environment. Use a tasteful media "
            "wall based on the real club crest and colors, clean architectural lighting and a credible transfer-announcement "
            "tone. Do not invent sponsors, partner logos or signatures."
        ),
        "motion_direction": (
            "Use one or two restrained distant press-camera flashes and a tiny ambient light shift. Keep the media wall, "
            "crest, typography and all supplied factual details perfectly stable and readable."
        ),
    },
    {
        "value": "country_city_identity",
        "label": "Identité pays / ville",
        "category": "Signature",
        "icon": "fa-location-dot",
        "summary": "Motifs locaux vérifiés et références culturelles discrètes.",
        "image_direction": (
            "Build a refined football portrait environment using at most two verified motifs from the club's city or the "
            "player's country. Blend them subtly with the real crest geometry and verified colors. Use no landmark, flag, "
            "animal, monument or cultural symbol unless it is explicitly verified from supplied or reliable sources."
        ),
        "motion_direction": (
            "Animate only environmental elements already present in the generated image: slow clouds or tiny distant birds "
            "when an outdoor sky exists, or a very subtle ambient light drift indoors. Never introduce a new cultural object."
        ),
    },
)


PRESENTATION_STYLE_CHOICES = tuple(
    (style["value"], style["label"])
    for style in PRESENTATION_STYLES
)


def get_presentation_style(value):
    """Return a valid style preset, falling back to the safe default."""
    for style in PRESENTATION_STYLES:
        if style["value"] == value:
            return style
    return next(
        style for style in PRESENTATION_STYLES
        if style["value"] == DEFAULT_PRESENTATION_STYLE
    )
