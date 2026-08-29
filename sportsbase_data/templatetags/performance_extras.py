from django import template

from sportsbase_data.analysis_engine import platform_index


register = template.Library()


STAT_LABELS = {
    "Index": "Index",
    "Matches played": "Matchs joués",
    "Time on the field, %": "Temps sur le terrain",
    "Minutes played": "Minutes jouées",
    "Goals": "Buts",
    "Assists": "Passes décisives",
    "Mistakes leading to goals": "Erreurs menant à un but",
    "Yellow cards": "Cartons jaunes",
    "Red cards": "Cartons rouges",
    "Key passes": "Passes clés",
    "Shots": "Tirs",
    "Crosses": "Centres",
    "Crosses accurate, %": "Centres réussis",
    "Passes": "Passes",
    "Passes accurate, %": "Passes réussies",
    "Challenges": "Duels",
    "Challenges won, %": "Duels gagnés",
    "Aerial challenges": "Duels aériens",
    "Aerial challenges won, %": "Duels aériens gagnés",
    "Dribbles": "Dribbles",
    "Dribbles successful, %": "Dribbles réussis",
    "Tackles": "Tacles",
    "Tackles successful, %": "Tacles réussis",
    "Interceptions": "Interceptions",
    "Loose ball recoveries": "Récupérations",
    "xG (expected goals)": "xG (buts attendus)",
    "Shots on target, %": "Tirs cadrés",
}


PORTAL_DATA_STATES = {
    "never": "Analyse en préparation",
    "queued": "Mise à jour planifiée",
    "running": "Mise à jour en cours",
    "success": "Données à jour",
    "partial": "Mise à jour en cours",
    "failed": "Actualisation en attente",
}


PORTAL_ACTION_STATES = {
    "not_requested": "À planifier",
    "queued": "Préparation planifiée",
    "generating": "Préparation en cours",
    "downloaded": "Vidéo disponible",
    "emailed": "Envoyée par e-mail",
    "failed": "Vérification en cours",
}


PORTAL_ACTION_MESSAGES = {
    "queued": "La compilation est planifiée par notre équipe.",
    "generating": "La compilation de toutes les actions est en préparation.",
    "downloaded": "La vidéo est prête et sera transmise selon le mode convenu.",
    "emailed": "La vidéo a été envoyée à l’adresse e-mail du compte.",
    "failed": "La livraison est en cours de vérification par notre équipe.",
}


PERFORMANCE_COPY = {
    "fr": {
        "home": "Mon espace",
        "performance": "Performance",
        "video_tracking": "Suivi vidéo",
        "performances_title": "Performances",
        "annual_subscription": "Abonnement annuel",
        "performance_centre": "Centre de performances",
        "performance_centre_help": "Statistiques de saison, cartes d’activité, matchs et livraisons All Actions.",
        "secure_analyses": "Analyses sécurisées",
        "production": "Production",
        "analysis": "Analyse",
        "authorized_players": "Joueurs autorisés",
        "active_subscriptions": "Mes abonnements actifs",
        "select_player_help": "Sélectionnez un joueur pour consulter sa saison et ses rencontres.",
        "matches_short": "matchs",
        "playing_time_short": "temps de jeu",
        "open_record": "Ouvrir la fiche",
        "no_active_subscription": "Aucun abonnement Performance actif",
        "activation_required": "MS Football doit activer ce service pour l’un de vos joueurs.",
        "last_update": "Dernière mise à jour",
        "analysis_preparing": "Analyse en préparation",
        "matches_played": "Matchs joués",
        "field_time": "Temps sur le terrain",
        "first_team": "Dans l’équipe première",
        "matches_analysed": "Matchs analysés",
        "videos_available": "vidéos disponibles dans votre espace",
        "analyses": "Analyses",
        "player_matches": "Matchs du joueur",
        "open_match": "Ouvrez une rencontre pour consulter les volumes, les taux de réussite, les cartes d’activité et le classement.",
        "index": "Index",
        "watch": "Regarder",
        "publishing": "Publication en cours",
        "planned": "Publication planifiée",
        "periodic_reviews": "Bilans périodiques",
        "five_match_cycles": "Évolution par cycles de cinq matchs",
        "cycle_help": "Chaque bilan met en évidence les tendances et les priorités du cycle suivant.",
        "match_analysis": "Analyse du match",
        "performance_summary": "Synthèse prioritaire",
        "direct_impact": "Impact décisif et évaluation",
        "analyst_verdict": "Opinion de l’analyste",
        "goals": "Buts",
        "assists": "Passes décisives",
        "key_passes": "Passes clés",
        "ms_score": "MS Score",
        "volume_efficiency": "Volume et efficacité",
        "efficiency_help": "Chaque volume d’action est associé directement à son taux de réussite.",
        "other_markers": "Autres repères du match",
        "positioning": "Positionnement",
        "activity_zones": "Zones d’activité",
        "involvement": "Implication",
        "ball_touches": "Touches de balle",
        "team_view": "Vue collective",
        "team_ranking": "Classement de l’équipe",
        "match_video": "Vidéo du match",
        "watch_actions": "Regarder All Actions",
        "actions_help": "Retrouvez toutes les actions du joueur dans cette rencontre.",
        "available": "Disponible",
        "open_video": "Ouvrir la vidéo",
        "pro_analysis": "Analyse professionnelle",
        "analyst_report": "Rapport de l’analyste",
        "report_help": "Consultez la synthèse, les points forts et les axes de progression retenus pour cette rencontre.",
        "download_pdf": "Télécharger le PDF",
        "date_unknown": "Date non renseignée",
        "participation_recorded": "Participation enregistrée",
        "referee": "Arbitre",
        "match_index": "Index du match",
        "global_indicator": "Indicateur global",
        "team_rank": "Classement équipe",
        "match_rank": "Classement du match",
        "both_teams": "Les deux équipes",
        "minutes_played": "Minutes jouées",
        "position_unknown": "Position non renseignée",
        "efficiency_preparing": "Les indicateurs d’efficacité sont en préparation.",
        "unavailable": "Non disponible.",
        "player": "Joueur",
        "position": "Poste",
        "minutes": "Minutes",
        "match_analysis_preparing": "Analyse du match en préparation",
        "indicators_preparing": "Les indicateurs apparaîtront ici dès qu’ils seront disponibles.",
        "actions_compilation": "Une seule compilation de toutes les actions du joueur pour cette rencontre.",
        "video_preparing": "La vidéo est en préparation par notre équipe.",
        "updated_on": "Mis à jour le",
        "no_match": "Aucun match disponible pour cette saison.",
        "secondary_info": "Informations secondaires",
        "player_record": "Fiche et repères du joueur",
        "profile": "Profil",
        "player_presentation": "Présentation du joueur",
        "birth_date": "Date de naissance",
        "contract_end": "Fin de contrat",
        "strong_foot": "Pied fort",
        "height_weight": "Taille / poids",
        "national_team": "Équipe nationale",
        "nationality": "Nationalité",
        "comparison": "Comparaison",
        "performance_radar": "Radar de performance",
        "radar_preparing": "Le radar sera affiché dès qu’il sera disponible.",
        "last_five_matches": "5 derniers matchs",
        "activity_maps": "Cartes d’activité",
        "map_preparing": "Carte en préparation.",
        "season_total": "Total saison",
        "statistics": "Statistiques",
        "season_analysis": "Analyse de la saison",
        "season_volume_efficiency": "Volume, efficacité et rythme",
        "season_efficiency_help": "Chaque volume saisonnier est relié à son taux de réussite et à sa moyenne par match.",
        "per_match": "par match",
        "other_season_markers": "Autres indicateurs de la saison",
        "other_averages": "Autres moyennes par match",
        "performance_pace": "Rythme de performance",
        "match_averages": "Moyennes par match",
        "no_season_stats": "Aucune statistique saisonnière disponible.",
        "no_averages": "Aucune moyenne disponible.",
        "detailed_view": "Vue détaillée",
        "season_table": "Tableau statistique de la saison",
        "rows": "lignes",
        "table_help": "Faites glisser horizontalement pour consulter tous les indicateurs de la saison.",
        "subscription_waiting": "L’abonnement est actif. Les premières données apparaîtront dès qu’elles seront disponibles.",
        "player_chart": "Joueur",
        "position_average": "Moyenne du poste",
        "subscription_payment": "Règlement de l’abonnement",
        "subscription_payment_help": "Suivez le prix, les règlements enregistrés et le solde de votre abonnement Performance.",
        "subscription_price": "Prix total",
        "amount_paid": "Déjà payé",
        "remaining_balance": "Solde restant",
        "pay_subscription": "Payer l’abonnement",
        "payment_complete": "Abonnement réglé",
    },
    "en": {
        "home": "My space",
        "performance": "Performance",
        "video_tracking": "Video tracking",
        "performances_title": "Performance",
        "annual_subscription": "Annual subscription",
        "performance_centre": "Performance centre",
        "performance_centre_help": "Season statistics, activity maps, matches and All Actions delivery.",
        "secure_analyses": "Secure analyses",
        "production": "Production",
        "analysis": "Analysis",
        "authorized_players": "Authorised players",
        "active_subscriptions": "My active subscriptions",
        "select_player_help": "Select a player to review their season and matches.",
        "matches_short": "matches",
        "playing_time_short": "playing time",
        "open_record": "Open profile",
        "no_active_subscription": "No active Performance subscription",
        "activation_required": "MS Football must activate this service for one of your players.",
        "last_update": "Last update",
        "analysis_preparing": "Analysis in preparation",
        "matches_played": "Matches played",
        "field_time": "Time on field",
        "first_team": "With the first team",
        "matches_analysed": "Matches analysed",
        "videos_available": "videos available in your space",
        "analyses": "Analyses",
        "player_matches": "Player matches",
        "open_match": "Open a match to review volumes, success rates, activity maps and rankings.",
        "index": "Index",
        "watch": "Watch",
        "publishing": "Publishing",
        "planned": "Publication planned",
        "periodic_reviews": "Periodic reviews",
        "five_match_cycles": "Five-match performance cycles",
        "cycle_help": "Each review highlights trends and priorities for the next cycle.",
        "match_analysis": "Match analysis",
        "performance_summary": "Priority summary",
        "direct_impact": "Decisive impact and assessment",
        "analyst_verdict": "Analyst opinion",
        "goals": "Goals",
        "assists": "Assists",
        "key_passes": "Key passes",
        "ms_score": "MS Score",
        "volume_efficiency": "Volume and efficiency",
        "efficiency_help": "Each action volume is directly paired with its success rate.",
        "other_markers": "Other match indicators",
        "positioning": "Positioning",
        "activity_zones": "Activity zones",
        "involvement": "Involvement",
        "ball_touches": "Ball touches",
        "team_view": "Team view",
        "team_ranking": "Team ranking",
        "match_video": "Match video",
        "watch_actions": "Watch All Actions",
        "actions_help": "Review every action by the player in this match.",
        "available": "Available",
        "open_video": "Open video",
        "pro_analysis": "Professional analysis",
        "analyst_report": "Analyst report",
        "report_help": "Review the summary, strengths and development priorities selected for this match.",
        "download_pdf": "Download PDF",
        "date_unknown": "Date not provided",
        "participation_recorded": "Participation recorded",
        "referee": "Referee",
        "match_index": "Match index",
        "global_indicator": "Overall indicator",
        "team_rank": "Team rank",
        "match_rank": "Match rank",
        "both_teams": "Both teams",
        "minutes_played": "Minutes played",
        "position_unknown": "Position not provided",
        "efficiency_preparing": "Efficiency indicators are being prepared.",
        "unavailable": "Unavailable.",
        "player": "Player",
        "position": "Position",
        "minutes": "Minutes",
        "match_analysis_preparing": "Match analysis in preparation",
        "indicators_preparing": "Indicators will appear here as soon as they are available.",
        "actions_compilation": "One compilation containing every action by the player in this match.",
        "video_preparing": "The video is being prepared by our team.",
        "updated_on": "Updated on",
        "no_match": "No match is available for this season.",
        "secondary_info": "Secondary information",
        "player_record": "Player profile and reference points",
        "profile": "Profile",
        "player_presentation": "Player presentation",
        "birth_date": "Date of birth",
        "contract_end": "Contract end",
        "strong_foot": "Strong foot",
        "height_weight": "Height / weight",
        "national_team": "National team",
        "nationality": "Nationality",
        "comparison": "Comparison",
        "performance_radar": "Performance radar",
        "radar_preparing": "The radar will appear as soon as it is available.",
        "last_five_matches": "Last 5 matches",
        "activity_maps": "Activity maps",
        "map_preparing": "Map in preparation.",
        "season_total": "Season total",
        "statistics": "Statistics",
        "season_analysis": "Season analysis",
        "season_volume_efficiency": "Volume, efficiency and rhythm",
        "season_efficiency_help": "Each season volume is paired with its success rate and per-match average.",
        "per_match": "per match",
        "other_season_markers": "Other season indicators",
        "other_averages": "Other per-match averages",
        "performance_pace": "Performance pace",
        "match_averages": "Per-match averages",
        "no_season_stats": "No season statistics are available.",
        "no_averages": "No averages are available.",
        "detailed_view": "Detailed view",
        "season_table": "Season statistics table",
        "rows": "rows",
        "table_help": "Swipe horizontally to review every season indicator.",
        "subscription_waiting": "The subscription is active. The first data will appear as soon as they are available.",
        "player_chart": "Player",
        "position_average": "Position average",
        "subscription_payment": "Subscription payment",
        "subscription_payment_help": "Review the price, recorded payments and the remaining balance of your Performance subscription.",
        "subscription_price": "Total price",
        "amount_paid": "Amount paid",
        "remaining_balance": "Remaining balance",
        "pay_subscription": "Pay subscription",
        "payment_complete": "Subscription paid",
    },
    "ar": {
        "home": "مساحتي",
        "performance": "الأداء",
        "video_tracking": "متابعة الفيديو",
        "performances_title": "الأداء",
        "annual_subscription": "الاشتراك السنوي",
        "performance_centre": "مركز الأداء",
        "performance_centre_help": "إحصائيات الموسم وخرائط النشاط والمباريات وفيديوهات جميع اللقطات.",
        "secure_analyses": "تحليلات آمنة",
        "production": "الإنتاج",
        "analysis": "التحليل",
        "authorized_players": "اللاعبون المصرح لهم",
        "active_subscriptions": "اشتراكاتي النشطة",
        "select_player_help": "اختر لاعباً للاطلاع على موسمه ومبارياته.",
        "matches_short": "مباريات",
        "playing_time_short": "وقت اللعب",
        "open_record": "فتح الملف",
        "no_active_subscription": "لا يوجد اشتراك أداء نشط",
        "activation_required": "يجب على MS Football تفعيل الخدمة لأحد لاعبيك.",
        "last_update": "آخر تحديث",
        "analysis_preparing": "التحليل قيد الإعداد",
        "matches_played": "المباريات الملعوبة",
        "field_time": "وقت اللعب",
        "first_team": "مع الفريق الأول",
        "matches_analysed": "المباريات المحللة",
        "videos_available": "فيديوهات متاحة في مساحتك",
        "analyses": "التحليلات",
        "player_matches": "مباريات اللاعب",
        "open_match": "افتح المباراة لمراجعة المؤشرات ونسب النجاح وخرائط النشاط والترتيب.",
        "index": "المؤشر",
        "watch": "مشاهدة",
        "publishing": "النشر جارٍ",
        "planned": "النشر مبرمج",
        "periodic_reviews": "التقارير الدورية",
        "five_match_cycles": "تطور الأداء كل خمس مباريات",
        "cycle_help": "يبرز كل تقرير التطور وأولويات دورة العمل القادمة.",
        "match_analysis": "تحليل المباراة",
        "performance_summary": "الخلاصة الأساسية",
        "direct_impact": "التأثير الحاسم والتقييم",
        "analyst_verdict": "رأي المحلل",
        "goals": "الأهداف",
        "assists": "التمريرات الحاسمة",
        "key_passes": "التمريرات المفتاحية",
        "ms_score": "MS Score",
        "volume_efficiency": "الحجم والنجاعة",
        "efficiency_help": "يرتبط حجم كل نشاط مباشرة بنسبة نجاحه.",
        "other_markers": "مؤشرات أخرى للمباراة",
        "positioning": "التمركز",
        "activity_zones": "مناطق النشاط",
        "involvement": "المشاركة",
        "ball_touches": "لمسات الكرة",
        "team_view": "نظرة جماعية",
        "team_ranking": "ترتيب الفريق",
        "match_video": "فيديو المباراة",
        "watch_actions": "مشاهدة جميع اللقطات",
        "actions_help": "راجع جميع لقطات اللاعب خلال هذه المباراة.",
        "available": "متاح",
        "open_video": "فتح الفيديو",
        "pro_analysis": "تحليل احترافي",
        "analyst_report": "تقرير المحلل",
        "report_help": "راجع الملخص ونقاط القوة ومحاور التطوير المحددة لهذه المباراة.",
        "download_pdf": "تحميل PDF",
        "date_unknown": "التاريخ غير متوفر",
        "participation_recorded": "تم تسجيل المشاركة",
        "referee": "الحكم",
        "match_index": "مؤشر المباراة",
        "global_indicator": "المؤشر العام",
        "team_rank": "الترتيب داخل الفريق",
        "match_rank": "الترتيب في المباراة",
        "both_teams": "الفريقان",
        "minutes_played": "دقائق اللعب",
        "position_unknown": "المركز غير متوفر",
        "efficiency_preparing": "مؤشرات النجاعة قيد الإعداد.",
        "unavailable": "غير متوفر.",
        "player": "اللاعب",
        "position": "المركز",
        "minutes": "الدقائق",
        "match_analysis_preparing": "تحليل المباراة قيد الإعداد",
        "indicators_preparing": "ستظهر المؤشرات هنا فور توفرها.",
        "actions_compilation": "فيديو واحد يجمع جميع لقطات اللاعب في هذه المباراة.",
        "video_preparing": "الفيديو قيد الإعداد من طرف فريقنا.",
        "updated_on": "آخر تحديث",
        "no_match": "لا توجد مباراة متاحة لهذا الموسم.",
        "secondary_info": "معلومات إضافية",
        "player_record": "بيانات اللاعب ومؤشراته",
        "profile": "الملف",
        "player_presentation": "تقديم اللاعب",
        "birth_date": "تاريخ الميلاد",
        "contract_end": "نهاية العقد",
        "strong_foot": "القدم المفضلة",
        "height_weight": "الطول / الوزن",
        "national_team": "المنتخب الوطني",
        "nationality": "الجنسية",
        "comparison": "المقارنة",
        "performance_radar": "رادار الأداء",
        "radar_preparing": "سيظهر الرادار فور توفره.",
        "last_five_matches": "آخر 5 مباريات",
        "activity_maps": "خرائط النشاط",
        "map_preparing": "الخريطة قيد الإعداد.",
        "season_total": "إجمالي الموسم",
        "statistics": "الإحصائيات",
        "season_analysis": "تحليل الموسم",
        "season_volume_efficiency": "الحجم والنجاعة والنسق",
        "season_efficiency_help": "يرتبط كل حجم موسمي بنسبة نجاحه ومعدله في المباراة.",
        "per_match": "في المباراة",
        "other_season_markers": "مؤشرات موسمية أخرى",
        "other_averages": "معدلات أخرى في المباراة",
        "performance_pace": "نسق الأداء",
        "match_averages": "معدلات كل مباراة",
        "no_season_stats": "لا توجد إحصائيات موسمية متاحة.",
        "no_averages": "لا توجد معدلات متاحة.",
        "detailed_view": "العرض المفصل",
        "season_table": "جدول إحصائيات الموسم",
        "rows": "أسطر",
        "table_help": "اسحب أفقيا للاطلاع على جميع مؤشرات الموسم.",
        "subscription_waiting": "الاشتراك نشط. ستظهر البيانات الأولى فور توفرها.",
        "player_chart": "اللاعب",
        "position_average": "معدل المركز",
        "subscription_payment": "دفع الاشتراك",
        "subscription_payment_help": "اطلع على سعر اشتراك الأداء والمبالغ المسجلة والرصيد المتبقي.",
        "subscription_price": "السعر الإجمالي",
        "amount_paid": "المبلغ المدفوع",
        "remaining_balance": "الرصيد المتبقي",
        "pay_subscription": "دفع الاشتراك",
        "payment_complete": "تم دفع الاشتراك",
    },
}


@register.filter
def stat_label(value):
    return STAT_LABELS.get(str(value), str(value))


@register.filter
def stat_label_for(value, language):
    value = str(value)
    if language == "fr":
        return STAT_LABELS.get(value, value)
    if language == "ar":
        from sportsbase_data.reports import METRIC_LABELS

        return METRIC_LABELS["ar"].get(value, value)
    return value


@register.filter
def stat_value(value):
    if value is None:
        return "—"
    if isinstance(value, str) and value.strip().casefold() in {
        "",
        "-",
        "–",
        "none",
        "null",
        "nan",
    }:
        return "—"
    return value


@register.filter
def ms_index(value):
    """Display every available index on the fixed MS platform scale."""
    return stat_value(platform_index(value))


@register.filter
def portal_data_state(value):
    return PORTAL_DATA_STATES.get(str(value), "Données disponibles")


@register.filter
def portal_action_label(value):
    return PORTAL_ACTION_STATES.get(str(value), "Suivi en cours")


@register.filter
def portal_action_message(value):
    return PORTAL_ACTION_MESSAGES.get(str(value), "")


@register.filter
def portal_data_state_for(value, language):
    translations = {
        "en": {
            "never": "Analysis in preparation",
            "queued": "Update scheduled",
            "running": "Update in progress",
            "success": "Data up to date",
            "partial": "Update in progress",
            "failed": "Update pending",
        },
        "ar": {
            "never": "التحليل قيد الإعداد",
            "queued": "التحديث مبرمج",
            "running": "التحديث جارٍ",
            "success": "البيانات محدثة",
            "partial": "التحديث جارٍ",
            "failed": "التحديث في الانتظار",
        },
    }
    if language == "fr":
        return PORTAL_DATA_STATES.get(str(value), "Données disponibles")
    return translations.get(str(language), {}).get(str(value), "Data available")


@register.filter
def portal_action_label_for(value, language):
    translations = {
        "en": {
            "not_requested": "To be scheduled",
            "queued": "Preparation scheduled",
            "generating": "Preparation in progress",
            "downloaded": "Video available",
            "emailed": "Sent by email",
            "failed": "Under review",
        },
        "ar": {
            "not_requested": "في انتظار البرمجة",
            "queued": "التحضير مبرمج",
            "generating": "التحضير جارٍ",
            "downloaded": "الفيديو متاح",
            "emailed": "تم الإرسال بالبريد الإلكتروني",
            "failed": "قيد المراجعة",
        },
    }
    if language == "fr":
        return PORTAL_ACTION_STATES.get(str(value), "Suivi en cours")
    return translations.get(str(language), {}).get(str(value), "Tracking in progress")


@register.filter
def portal_action_message_for(value, language):
    translations = {
        "en": {
            "queued": "The compilation has been scheduled by our team.",
            "generating": "The compilation of every action is being prepared.",
            "downloaded": "The video is ready and will be delivered as agreed.",
            "emailed": "The video was sent to the account email address.",
            "failed": "The delivery is being reviewed by our team.",
        },
        "ar": {
            "queued": "تمت برمجة إعداد الفيديو من طرف فريقنا.",
            "generating": "يجري إعداد فيديو جميع اللقطات.",
            "downloaded": "الفيديو جاهز وسيتم إرساله بالطريقة المتفق عليها.",
            "emailed": "تم إرسال الفيديو إلى البريد الإلكتروني للحساب.",
            "failed": "عملية الإرسال قيد المراجعة من طرف فريقنا.",
        },
    }
    if language == "fr":
        return PORTAL_ACTION_MESSAGES.get(str(value), "")
    return translations.get(str(language), {}).get(str(value), "")


@register.simple_tag
def performance_copy(language):
    return PERFORMANCE_COPY.get(str(language), PERFORMANCE_COPY["fr"])


@register.filter
def dict_get(value, key):
    if not isinstance(value, dict):
        return None
    return value.get(key)
