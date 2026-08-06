# source_data.py
#
# Hand-transcribed from the three source PDFs ("Staff and client details
# (1).pdf" = employee master, "Staff and client details.pdf" = client
# hierarchy, "Client_emails.pdf" = client contact emails). Kept as plain
# data, deliberately free of any role/category/hierarchy logic (that
# lives in mapping.py) so this file stays a faithful transcript that's
# easy to diff against the source PDFs if they're ever corrected.

# --------------------------------------------------------------------
# Dataset 1: Employee Master
# --------------------------------------------------------------------
# Each row: (employee_id, name, designation, email, reporting_manager_raw, process)
# reporting_manager_raw is the exact text from the "Reporting Manager"
# column — may be a real employee's name (possibly spelled/ordered
# differently than their own Name column — see REPORTING_MANAGER_ALIASES
# below), or a non-employee sentinel ("ProbeRCM").

EMPLOYEES = [
    (266, "Christopher Johnson", "Sr. AR Associate", "christopher@painmedpa.com", "Jayaneethan Shanmugarajah", "AR"),
    (278, "Vetri Guhan", "Trainee - AR Executive", "vetri@painmedpa.com", "Jayaneethan Shanmugarajah", "AR"),
    (279, "Justin Wilson", "Trainee - AR Executive", "justin@painmedpa.com", "Jayaneethan Shanmugarajah", "AR"),
    (265, "Bharathihasan Kumar", "AR Associate", "bharathihasan@painmedpa.com", "Jayaneethan Shanmugarajah", "AR"),
    (237, "Syed Reehan", "Referral Coordinator", "reehan@probeps.com", "John Abilash", "Referral"),
    (225, "Anish A", "Referral Coordinator", "anish@probeps.com", "John Abilash", "Referral"),
    (212, "Balraj Gowda K", "Referral Coordinator", "balraj@probeps.com", "John Abilash", "Referral"),
    (263, "Kushal B", "Referral Coordinator - Trainee", "kushal.b@probeps.com", "John Abilash", "Referral"),
    (213, "Fairoz Khan", "AR Associate", "fairoz@probeps.com", "Kamaleshwaran K", "AR"),
    (125, "Chethan S", "Analyst - AR & Denials", "chethan.s@probeps.com", "Kamaleshwaran K", "AR"),
    (227, "Lakshmi R", "AR Associate", "lakshmi.r@probeps.com", "Kamaleshwaran K", "AR"),
    (99, "Vinay S", "AR Associate", "vinay@probeps.com", "Kamaleshwaran K", "AR"),
    (43, "Mahesh Kumar J", "Analyst - AR & Denials", "mahesh@probeps.com", "Kamaleshwaran K", "AR"),
    (174, "Shaziya Begum", "Sr. AR Associate", "shaziya@probeps.com", "Kamaleshwaran K", "AR"),
    (161, "Akshatha M", "Authorization Associate", "akshatha.m@probeps.com", "Kamaleshwaran K", "Authorization"),
    (186, "Ravi Chandra P", "Authorization Associate", "ravichandra@probeps.com", "Kamaleshwaran K", "Authorization"),
    (183, "Ramalingu P", "Authorization Associate", "ramalingu@probeps.com", "Kamaleshwaran K", "Authorization"),
    (31, "Rashmi M", "Sr Insurance Verification Associate", "rashmi@probeps.com", "Kamaleshwaran K", "IV"),
    (281, "Pratham Gowda M", "Trainee - Insurance verification Associate", "pratham@probeps.com", "Kamaleshwaran K", "IV"),
    (217, "Jedson V", "Insurance verification Associate", "jedson@probeps.com", "Kamaleshwaran K", "IV"),
    (290, "Raziq Baig M R", "0", "raziq@probeps.com", "Kamaleshwaran K", "IV"),
    (38, "Rajendra Prasad M", "Team Lead - AR", "rajendra@probeps.com", "Kamaleshwaran K", "Lead - AR"),
    (276, "Sanjay P", "Trainee - Credentialing Executive", "sanjay@probeps.com", "Koushik P V", "Credentialing"),
    (280, "Savitha C", "Credentialing Specialist", "savitha@probeps.com", "Koushik P V", "Credentialing"),
    (207, "Pavan T", "Referral Coordinator", "pavan.t@probeps.com", "Koushik P V", "Credentialing"),
    (2, "Umesh J", "Director of Operations", "umesh@probeps.com", "ProbeRCM", "Director"),
    (226, "Marpina Yaswanth Sai", "AR Associate Trainee - Non Voice", "yashwanth@probeps.com", "Sadatulla Gaffar", "AR"),
    (257, "Belliappa P M", "AR Associate", "belliappa@probeps.com", "Sadatulla Gaffar", "AR"),
    (291, "Syed Rafiq", "0", "rafiq@probeps.com", "Sadatulla Gaffar", "AR"),
    (106, "Anthony Clinton", "Insurance verification Associate", "anthony@probeps.com", "Sadatulla Gaffar", "AR"),
    (240, "Kishore Kumar B", "Insurance verification Associate", "kishore@probeps.com", "Sadatulla Gaffar", "IV"),
    (277, "Likhith S N", "AR Associate", "likhith@probeps.com", "Sahana Paul", "AR"),
    (156, "Hemanth M U", "AR Associate", "hemanth@probeps.com", "Sahana Paul", "AR"),
    (60, "Premkumar V", "Sr. AR Associate", "prem@probeps.com", "Satish H R", "AR"),
    (122, "Navaneeth S", "Insurance verification Associate", "navaneeth@probeps.com", "Satish H R", "AR"),
    (273, "Yesudas V", "Sr. AR Associate", "yesudas@probeps.com", "Satish H R", "AR"),
    (118, "Ummer Farooq Ahmed", "Analyst - AR & Denials", "ummer@probeps.com", "Satish H R", "AR"),
    (261, "Mahmad Asif", "AR Associate", "mahmad@probeps.com", "Satish H R", "AR"),
    (159, "Ponnamma A M", "Insurance verification Associate", "ponnamma@probeps.com", "Satish H R", "IV"),
    (157, "Punyashree K", "Insurance verification Associate", "punyashree@probeps.com", "Satish H R", "IV"),
    (65, "Raghunandan B", "Associate Lead - AR", "raghunandan@probeps.com", "Satish H R", "Lead - AR"),
    (204, "Sowmya Shree B", "Sr Team Lead - Payment Posting", "sowmyashree@probeps.com", "Satish H R", "Lead - Payment Posting"),
    (28, "Madhura K", "Medical Coding Associate", "madhura@probeps.com", "Sindhushree S", "Coding"),
    (87, "Madhushree G", "Jr Medical Coder", "madhushree@probeps.com", "Sindhushree S", "Coding"),
    (256, "Inchara K A", "Trainee - Medical Coder", "inchara@probeps.com", "Sindhushree S", "Coding"),
    (214, "Kavyashree G", "Jr Medical Coder", "kavyashree@probeps.com", "Sindhushree S", "Coding"),
    (182, "Apeksha M", "Trainee - Authorization Associate", "apeksha@probeps.com", "Sindhushree S", "Coding"),
    (216, "Pavani G", "Medical Coding Associate", "pavani@probeps.com", "Sindhushree S", "Coding"),
    (184, "Pradeep M S", "Medical Coding Associate", "pradeep.ms@probeps.com", "Sindhushree S", "Coding"),
    (58, "Sushmitha C K", "Medical Coding Associate", "sushmitha@probeps.com", "Sindhushree S", "Coding"),
    (177, "Deepthi M G", "Trainee - Authorization Associate", "deepthi@probeps.com", "Sindhushree S", "Coding"),
    (185, "Shameem K I", "Jr Medical Coder", "shameem@probeps.com", "Sindhushree S", "Coding"),
    (89, "shreya C", "Jr Medical Coder", "shreya@probeps.com", "Sindhushree S", "Coding"),
    (152, "chandana H R", "Jr Medical Coder", "chandana.hr@probeps.com", "Sindhushree S", "Coding"),
    (160, "Shwetha M R", "Jr Medical Coder", "shwetha.mr@probeps.com", "Sindhushree S", "Coding"),
    (69, "Bhuvana C K", "Medical Coding Associate", "bhuvana@probeps.com", "Sindhushree S", "Coding"),
    (198, "Chandan N", "Insurance verification Associate", "chandan.n@probeps.com", "Sowmya Shree B", "IV"),
    (26, "Malathi C", "Sr Payment Posting Associate", "malathi@probeps.com", "Sowmya Shree B", "Payment Posting"),
    (153, "Pavan Raj N", "Sr Payment Posting Associate", "pavan@probeps.com", "Sowmya Shree B", "Payment Posting"),
    (272, "Dayananda Reddy", "Sr Payment Posting Associate", "dayananda@probeps.com", "Sowmya Shree B", "Payment Posting"),
    (33, "Rashmi R", "Sr Payment Posting Associate", "rashmi.r@probeps.com", "Sowmya Shree B", "Payment Posting"),
    (292, "Mohammed Afwan M M", "0", "afwan@probeps.com", "Subramanya M P", "IV"),
    (252, "Praveen Baligar", "Authorization Associate", "praveen.baligar@probeps.com", "Umesh J", "Authorization"),
    (113, "Kugasri D N", "Authorization Associate", "kugasri@probeps.com", "Umesh J", "Authorization"),
    (42, "Akshay C", "Authorization Specialist", "akshay@probeps.com", "Umesh J", "Authorization"),
    (259, "Srinivas Agollu", "Quality Analyst - Coding", "srinivas@probeps.com", "Umesh J", "Coding"),
    (71, "Paul Sahana", "Associate Lead - AR", "paul.sahana@probeps.com", "Umesh J", "Lead - AR"),
    (264, "Jayaneethan Shanmugarajah", "Team Lead - AR", "jay@painmedpa.com", "Umesh J", "Lead - AR"),
    (176, "Sindhushree S", "Team Lead - Medical Coding", "sindhushree@probeps.com", "Umesh J", "Lead - Coding"),
    (110, "Yashodha S", "Sr Team Lead", "yashodha@probeps.com", "Umesh J", "Lead - Quality and Payment Posting"),
    (146, "John Abilash", "Referral Coordinator", "john@probeps.com", "Umesh J", "Lead - Referral"),
    (66, "Koushik P V", "Manager - Credentialing", "koushik@probeps.com", "Umesh J", "Manager"),
    (190, "Satish H R", "Manager - Operations", "satish@probeps.com", "Umesh J", "Manager"),
    (24, "Kamaleshwaran K", "Account Manager", "kamalesh@probeps.com", "Umesh J", "Manager"),
    (102, "Sadatulla Gaffar", "Account Manager", "sadath@probeps.com", "Umesh J", "Manager"),
    (231, "Subramanya Prasad M P", "Trainer", "subramanya@probeps.com", "Umesh J", "Trainer"),
    (196, "Swarna Gowri S", "AR Associate Trainee - Non Voice", "swarnagowri@probeps.com", "Yashodha S", "AR"),
    (194, "Poorva C V", "AR Associate Trainee - Non Voice", "poorva@probeps.com", "Yashodha S", "AR"),
    (195, "Pavana M", "AR Associate Trainee - Non Voice", "pavana.m@probeps.com", "Yashodha S", "AR"),
    (189, "shukrutha N", "AR Associate Trainee - Non Voice", "shukrutha@probeps.com", "Yashodha S", "AR"),
    (191, "Deepthi Kadli P", "AR Associate Trainee - Non Voice", "deepthi.pk@probeps.com", "Yashodha S", "AR"),
    (192, "Varshitha D", "AR Associate Trainee - Non Voice", "varshitha@probeps.com", "Yashodha S", "AR"),
    (205, "Mithun R", "AR Associate Trainee - Non Voice", "mithun.r@probeps.com", "Yashodha S", "AR"),
    (78, "Mallikarjuna Raje urs S N", "Jr Medical Coder", "mallikarjuna@probeps.com", "Yashodha S", "Coding"),
    (201, "Pooja M", "Insurance verification Associate", "pooja.m@probeps.com", "Yashodha S", "IV"),
    (210, "Chandana L", "Insurance verification Associate", "chandana.l@probeps.com", "Yashodha S", "IV"),
    (233, "Venkatesh S Katti", "Insurance verification Associate", "venkatesh@probeps.com", "Yashodha S", "IV"),
    (206, "Prashanth N", "Insurance verification Associate", "prashanth@probeps.com", "Yashodha S", "IV"),
    (199, "Vinay Suresh", "Insurance verification Associate", "vinay.s@probeps.com", "Yashodha S", "IV"),
    (141, "Manasa L", "Insurance verification Associate", "manasa@probeps.com", "Yashodha S", "IV"),
    (13, "Spoorthi K", "Sr Payment Posting Associate", "spoorthi@probeps.com", "Yashodha S", "Payment Posting"),
    (44, "Preksha SR", "Sr Payment Posting Associate", "preksha@probeps.com", "Yashodha S", "Payment Posting"),
    (253, "Dhrithi B K", "Payment Posting Associate", "dhrithi@probeps.com", "Yashodha S", "Payment Posting"),
    (27, "Vishma PD", "Sr Payment Posting Associate", "vishma@probeps.com", "Yashodha S", "Payment Posting"),
    (94, "Pooja Gowtham K", "Payment Posting Associate", "pooja.k@probeps.com", "Yashodha S", "Payment Posting"),
    (12, "Yashaswi K", "Payment Posting - Quality Analyst", "yashaswi@probeps.com", "Yashodha S", "Quality"),
    (175, "Ananya S", "Quality Analyst - AR & Authorization", "ananya@probeps.com", "Yashodha S", "Quality"),
    (19, "Kajol MA", "Quality Analyst - IV", "kajol@probeps.com", "Yashodha S", "Quality"),
    (289, "Afreen Taj", "Quality Analyst - AR & Authorization", "afreen@probeps.com", "Yashodha S", "Quality"),
]

# Reporting-Manager text that doesn't exactly match the referenced
# employee's own Name column, plus non-employee sentinels. Keys are the
# raw "Reporting Manager" text as it appears in EMPLOYEES; values are
# either the canonical Name of the actual employee, or None for a
# sentinel that isn't a person at all (never resolved to a user).
REPORTING_MANAGER_ALIASES = {
    "ProbeRCM": None,  # company name, not a person — Umesh J is the top of the hierarchy
    "Sahana Paul": "Paul Sahana",  # same person as employee 71, name order reversed
    "Subramanya M P": "Subramanya Prasad M P",  # same person as employee 231, name truncated
}

# --------------------------------------------------------------------
# Dataset 2: Client Hierarchy
# --------------------------------------------------------------------
# Each row: (client_name, manager_alias, ar_lead_alias, coding_lead_alias, posting_lead_alias)
# "-" in the source PDF means missing -> None here. Aliases are resolved
# to a canonical employee Name via CLIENT_PERSON_ALIASES below (the
# client sheet uses first-names/shorthand, not full Employee Master names).

CLIENTS = [
    ("APM", "Kamal", "Rajendra Prasad", "Sindhushree", "Yashodha"),
    ("East West Pain Institute", "Kamal", "Rajendra Prasad", "Sindhushree", "Yashodha"),
    ("FFJ", "Kamal", "Rajendra Prasad", "Sindhushree", "Yashodha"),
    ("CPC", "Kamal", "Rajendra Prasad", "Sindhushree", None),
    ("MMC", "Kamal", "Rajendra Prasad", "Sindhushree", None),
    ("PCRR", "Sadath", None, "Sindhushree", "Yashodha"),
    ("HEEL & SOLE FOOT & ANKLE, PLLC", "Sadath", None, "Sindhushree", "Sowmyashree"),
    ("Sekel Health", "Sadath", None, "Sindhushree", "Sowmyashree"),
    ("CTFS", "Satish", "Raghunandan", "Sindhushree", "Sowmyashree"),
    ("ATX 360 PM", "Satish", "Raghunandan", "Sindhushree", "Sowmyashree"),
    ("Taral Sharma MD PA", "Satish", "Raghunandan", "Sindhushree", "Sowmyashree"),
    ("Nexus Pain care LLC", "Satish", "Raghunandan", "Sindhushree", "Sowmyashree"),
    ("Compassionate Womens health", "Umesh", "Sahana Paul", "Sindhushree", "Yashodha"),
    ("Cameron pediatrics", "Umesh", "Sahana Paul", "Sindhushree", "Yashodha"),
    ("LEFC", "Umesh", "Sahana Paul", "Sindhushree", "Yashodha"),
    ("Performance Ortho", "Umesh", "Subramanya", None, None),
]

# Client-sheet shorthand -> canonical Employee Master Name (see EMPLOYEES above).
CLIENT_PERSON_ALIASES = {
    "Kamal": "Kamaleshwaran K",
    "Sadath": "Sadatulla Gaffar",
    "Satish": "Satish H R",
    "Umesh": "Umesh J",
    "Rajendra Prasad": "Rajendra Prasad M",
    "Raghunandan": "Raghunandan B",
    "Sahana Paul": "Paul Sahana",
    "Sindhushree": "Sindhushree S",
    "Yashodha": "Yashodha S",
    "Sowmyashree": "Sowmya Shree B",
    "Subramanya": "Subramanya Prasad M P",
}

# --------------------------------------------------------------------
# Dataset 3: Client Contact Emails
# --------------------------------------------------------------------
# client_name -> list of contact emails, in the order given in the PDF
# (order matters: the first non-internal address is the default pick
# for clients.inbox_email — see mapping.PRIMARY_CONTACT_OVERRIDE for the
# two clients where that default is wrong).

CLIENT_CONTACTS = {
    "APM": [
        "maria@advpainmod.com", "mariela@advpainmod.com", "caroline@advpainmod.com",
        "drlgollapalli@advpainmod.com", "chelsea@advpainmod.com", "admin@advpainmod.com",
        "alberto@advpainmod.com", "kimberly@advpainmod.com", "mackenzie@advpainmod.com",
        "ashley@advpainmod.com", "amanda@advpainmod.com", "kady@advpainmod.com",
        "lisdy@advpainmod.com", "shalena@advpainmod.com", "janett@advpainmod.com",
        "ava@advpainmod.com", "bryan@advpainmod.com",
    ],
    "East West Pain Institute": [
        "swainlynn@outlook.com", "lynngreen18@gmail.com", "shuchakrausa@yahoo.com",
    ],
    "FFJ": [
        "Katie@probeps.com", "lisa@familyfirstjville.com", "sherri@familyfirstjville.com",
        "barbara@familyfirstjville.com", "caseyd@familyfirstjville.com", "DanielP@familyfirstjville.com",
    ],
    "CPC": [
        "aglass@carolinaspaincenter.com", "bshah@carolinaspaincenter.com",
    ],
    "MMC": [
        "spatel@metroplex-medical.com", "spatel@griegomedical.com", "dgonzales@metroplex-medical.com",
        "KLopez@metroplex-medical.com", "pbarron@metroplex-medical.com", "LPeterson@metroplex-medical.com",
        "LLopez@metroplex-medical.com", "mManeha@metroplex-medical.com", "vHernandez@metroplex-medical.com",
        "MPatel@metroplex-medical.com",
    ],
    "PCRR": [
        "emily@probeps.com", "bhargavibkola@gmail.com", "vivekanand.dasari@gmail.com",
        "cindy@probeps.com", "raj@probeps.com",
    ],
    "HEEL & SOLE FOOT & ANKLE, PLLC": [
        "robinsonchandra33@yahoo.com", "srobinson2695@gmail.com", "krobinson2694@gmail.com",
    ],
    "Sekel Health": [
        "sekelhealth@gmail.com",
    ],
    "CTFS": [
        "drpietzsch@centexfoot.com", "liza@centexfoot.com",
    ],
    "ATX 360 PM": [
        "bpulikal@atx360pain.com", "apulikal@atx360pain.com", "lparsons@atx360pain.com",
        "jtoledo@atx360pain.com", "charper@atx360pain.com",
    ],
    "Taral Sharma MD PA": [
        "tsharma@carolinapsychiatry.com", "kblack@taralsharmamd.com", "ktolliver@carolinapsychiatry.com",
        "aoliver@carolinapsychiatry.com", "jgilliam@carolinapsychiatry.com", "lking@carolinapsychiatry.com",
        "bmcnair@carolinapsychiatry.com", "awhitfield@carolinapsychiatry.com", "referral@carolinapsychiatry.com",
        "cgoss@carolinapsychiatry.com", "kfuller@carolinapsychiatry.com", "va1@carolinapsychiatry.com",
        "sfuller@carolinapsychiatry.com", "coordinator@carolinapsychiatry.com", "kimowen@carolinapsychiatry.com",
    ],
    "Nexus Pain care LLC": [
        "maryamismail32@gmail.com",
    ],
    "Compassionate Womens health": [
        "alejandra.rodriguez@compassionatewomenshealth.com", "harsh.adhyaru@compassionatewomenshealth.com",
    ],
    "Cameron pediatrics": [
        "cameronpeds@gmail.com",
    ],
    "LEFC": [
        "lefclinic@yahoo.com", "lefpediatrics@gmail.com",
    ],
    "Performance Ortho": [
        "afarley@performanceortho.com", "ksanczyk@performanceortho.com",
        "mmatthews@performanceortho.com", "smaziarz@performanceortho.com",
    ],
}
