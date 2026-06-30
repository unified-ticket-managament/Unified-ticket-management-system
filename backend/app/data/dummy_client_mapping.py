from uuid import UUID

CLIENT_ASSIGNMENTS = {
    "abcclinic@gmail.com": {
        "client_id": UUID("11111111-1111-1111-1111-111111111111"),
        "client_name": "ABC Clinic",
        "agent_id": UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        "agent_name": "Agent A",
    },
    "xyzclinic@gmail.com": {
        "client_id": UUID("22222222-2222-2222-2222-222222222222"),
        "client_name": "XYZ Clinic",
        "agent_id": UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        "agent_name": "Agent B",
    },
    "lmnclinic@gmail.com": {
        "client_id": UUID("33333333-3333-3333-3333-333333333333"),
        "client_name": "LMN Clinic",
        "agent_id": UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
        "agent_name": "Agent C",
    },
}