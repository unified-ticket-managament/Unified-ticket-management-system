# Test Emails — Healthcare RCM Scenarios

Synthetic test fixtures for exercising the ticket-management system's email intake (inbound webhook, threading, ticket creation, SLA clocks). All names, patients, claim numbers, dollar amounts, and organizations below are **fictional** — invented for testing only, not real correspondence or real entities.

Categories: Claim Status, Claim Denial, Payment Posting, Eligibility, Prior Authorization, Referral, Missing Documents, Insurance Follow-up, Appointment Scheduling, Billing Questions, Revenue Reports, Vendor Requests.

---

## Claim Status

### 1. Status check — outstanding claim over 30 days
**Subject:** Status Request — Claim #CLM-88213 (DOS 05/12/2026)
**From:** rachel.tanner@meridianhealthplans.com
**To:** billing@painmedpa.com
**Body:**
Hello,

We're following up on claim #CLM-88213 submitted on 05/14/2026 for date of service 05/12/2026, patient J. Alvarez (Member ID MHP-40218856). Our system shows the claim as "received" but not yet adjudicated after 30+ days.

Can you confirm whether any additional information is needed on our end, or provide an updated timeline for adjudication?

Thank you,
Rachel Tanner
Provider Relations, Meridian Health Plans

---

### 2. Internal status inquiry from front desk
**Subject:** Any update on the Nguyen claim?
**From:** frontdesk@painmedpa.com
**To:** billing@painmedpa.com
**Body:**
Hi team,

Patient Linh Nguyen called asking whether her claim from the 06/02 visit has been processed yet. She's getting a bill from us but says her insurance hasn't shown anything on their end. Can someone check the status and let me know what to tell her if she calls back?

Thanks,
Front Desk — Main Office

---

### 3. Clearinghouse rejection status
**Subject:** Claim Status — Rejected at Clearinghouse (Batch 20260614-A)
**From:** noreply@claimlinkexchange.com
**To:** billing@painmedpa.com
**Body:**
This is an automated notice from ClaimLink Exchange.

The following claim was rejected during pre-adjudication scrubbing and was NOT forwarded to the payer:

- Claim ID: CL-773410
- Patient: D. Whitfield
- Payer: Continental Care Insurance
- Rejection Reason: Invalid Rendering Provider NPI

Please correct and resubmit. This claim will not be automatically retried.

ClaimLink Exchange Batch Processing

---

## Claim Denial

### 4. Denial for lack of medical necessity
**Subject:** Denial Notice — Claim #CLM-90144 (CO-50)
**From:** appeals@continentalcareins.com
**To:** billing@painmedpa.com
**Body:**
Dear Provider,

Claim #CLM-90144 for patient M. Reyes, date of service 04/28/2026, has been denied with reason code CO-50: "These are non-covered services because this is not deemed a medical necessity by the payer."

Procedure billed: 64483 (transforaminal epidural injection, lumbar)

If you believe this denial was made in error, you have 90 days from this notice to submit a written appeal with supporting clinical documentation.

Continental Care Insurance
Appeals Department

---

### 5. Duplicate claim denial
**Subject:** RE: Claim #CLM-90201 — Denied as Duplicate
**From:** claims@blueshieldadvantage.com
**To:** billing@painmedpa.com
**Body:**
Hello,

Claim #CLM-90201 (patient S. Okafor, DOS 05/03/2026) was denied with code CO-18 — exact duplicate of claim #CLM-89977, which was already paid on 05/20/2026.

If you believe these are two distinct, separately billable encounters, please resubmit with documentation distinguishing the two dates of service.

BlueShield Advantage Claims Processing

---

### 6. Internal note flagging a denial trend
**Subject:** Increase in CO-97 denials this month — need to review
**From:** priya.desai@painmedpa.com
**To:** billing@painmedpa.com
**Body:**
Hi all,

I've noticed at least 6 claims denied this month with CO-97 ("benefit included in payment for another service already adjudicated") specifically for our fluoroscopy add-on codes billed alongside injections. This looks like a bundling issue on a few payers' side, not a documentation problem.

Can someone pull the full list from the last 30 days so we can decide whether to appeal in bulk or adjust our billing pattern?

Thanks,
Priya Desai
Billing Supervisor

---

## Payment Posting

### 7. ERA payment notification
**Subject:** Payment Remittance Available — ERA #ERA-2026-061205
**From:** remittance@meridianhealthplans.com
**To:** payments@painmedpa.com
**Body:**
An Electronic Remittance Advice is now available for download.

- ERA Number: ERA-2026-061205
- Payment Date: 06/12/2026
- Total Paid: $4,812.40
- Claims Included: 11
- Payment Method: EFT — Trace #884213765

Please log in to the Meridian Provider Portal to download the full 835 file.

Meridian Health Plans, Remittance Services

---

### 8. Posting discrepancy question from staff
**Subject:** EFT amount doesn't match the 835 line items
**From:** carla.jimenez@painmedpa.com
**To:** billing@painmedpa.com
**Body:**
Hi,

I'm posting the EFT from Continental Care (trace #CCI-559812, $2,140.00) but the sum of the individual claim line items in the 835 only adds up to $2,015.00. There's a $125.00 gap I can't account for — could be a withhold or an offset for a prior overpayment, but I don't see a note explaining it.

Can someone with payer portal access check if there's an adjustment memo attached to this payment?

Thanks,
Carla Jimenez
Payment Posting

---

### 9. Patient payment confirmation
**Subject:** Payment Confirmation — Invoice #INV-31820
**From:** patientpay@painmedpa.com
**To:** t.harmon.patient@gmail.com
**Body:**
Dear Mr. Harmon,

This confirms we received your payment of $85.00 on 06/10/2026 toward invoice #INV-31820 for your visit on 05/22/2026. Your remaining balance after this payment is $0.00.

Thank you for your prompt payment. If you have any questions about this statement, please reply to this email or call our billing office.

PainMed Physicians Group
Patient Accounts

---

## Eligibility

### 10. Eligibility verification request (internal, pre-visit)
**Subject:** Please verify eligibility — appt tomorrow 8:30am
**From:** scheduling@painmedpa.com
**To:** eligibility@painmedpa.com
**Body:**
Hi team,

Can you verify eligibility for the following patient ahead of tomorrow's 8:30am appointment?

- Patient: G. Petrova
- DOB: 03/14/1979
- Insurance: BlueShield Advantage
- Member ID: BSA-772140093

She mentioned she may have switched plans recently through her employer, so please double check active coverage and whether a referral is on file.

Thanks,
Scheduling Desk

---

### 11. Payer response — coverage termed
**Subject:** RE: Eligibility Inquiry — Member ID MHP-40218856
**From:** eligibility@meridianhealthplans.com
**To:** eligibility@painmedpa.com
**Body:**
Thank you for your inquiry.

Coverage for Member ID MHP-40218856 (J. Alvarez) was termed effective 05/01/2026 due to non-payment of premium. There is currently no active plan on file for this member with Meridian Health Plans.

If the patient has obtained new coverage, please resubmit your inquiry with the updated member information.

Meridian Health Plans
Eligibility Services

---

### 12. Self-pay conversion notice
**Subject:** Patient eligibility lapsed — convert to self-pay?
**From:** eligibility@painmedpa.com
**To:** frontdesk@painmedpa.com
**Body:**
Hi,

We ran eligibility for patient R. Okonkwo's visit next week and her Continental Care plan shows as inactive since 04/01/2026. I left a voicemail for her but haven't heard back.

Should we register tomorrow's visit as self-pay for now, or hold the appointment until she confirms new coverage? Let me know how you'd like to handle it at check-in.

Thanks,
Eligibility Team

---

## Prior Authorization

### 13. Auth request submitted
**Subject:** Prior Auth Submitted — Lumbar RFA, Patient K. Sandoval
**From:** priorauth@painmedpa.com
**To:** authreview@continentalcareins.com
**Body:**
To Whom It May Concern,

We are submitting a request for prior authorization for the following procedure:

- Patient: K. Sandoval, Member ID CCI-661203
- Procedure: CPT 64635/64636 — Radiofrequency ablation, lumbar facet joints, bilateral L4-S1
- Requested Date of Service: 06/25/2026
- Ordering Provider: Dr. A. Whitmore, NPI 1234567890

Clinical documentation, including two prior successful diagnostic medial branch blocks, is attached. Please confirm receipt and expected turnaround time.

PainMed Physicians Group
Prior Authorization Department

---

### 14. Auth approved with conditions
**Subject:** Authorization Approved — Auth #AUTH-773341
**From:** authreview@continentalcareins.com
**To:** priorauth@painmedpa.com
**Body:**
This confirms authorization has been approved for the following:

- Authorization Number: AUTH-773341
- Patient: K. Sandoval
- Procedure: CPT 64635/64636
- Approved Visits: 1
- Valid From: 06/20/2026 To: 08/20/2026

Please note: authorization is valid only for the specific levels and side(s) indicated in the original request. Any deviation at time of service may result in claim denial.

Continental Care Insurance
Utilization Management

---

## Referral

### 15. Incoming referral from PCP
**Subject:** New Patient Referral — Chronic Low Back Pain
**From:** referrals@lakesideprimarycare.com
**To:** referrals@painmedpa.com
**Body:**
Hello,

Please accept the attached referral for our patient, T. Blackwood, for evaluation and management of chronic low back pain with radiculopathy, unresponsive to conservative care over the last 4 months.

Relevant history, current medication list, and most recent lumbar MRI report (04/2026) are attached. Please contact our office if any additional records are needed.

Dr. S. Okafor, MD
Lakeside Primary Care

---

### 16. Referral status inquiry from referring office
**Subject:** Following up on referral for patient Blackwood
**From:** referrals@lakesideprimarycare.com
**To:** referrals@painmedpa.com
**Body:**
Hi,

We sent a referral for patient T. Blackwood about two weeks ago and haven't heard back regarding a scheduled appointment. Could you confirm it was received and let us know the appointment status? The patient has called our office twice asking for an update.

Thank you,
Lakeside Primary Care — Referral Coordinator

---

## Missing Documents

### 17. Payer requesting additional records
**Subject:** Additional Documentation Required — Claim #CLM-90144
**From:** appeals@continentalcareins.com
**To:** billing@painmedpa.com
**Body:**
To complete review of claim #CLM-90144, the following documentation is required:

- Complete office visit note for DOS 04/28/2026
- Documentation of at least 6 weeks of conservative treatment failure
- Prior imaging report referenced in the procedure note

Please submit within 30 days of this request or the claim will remain denied without further review.

Continental Care Insurance
Medical Review Unit

---

### 18. Internal chase for missing chart note
**Subject:** Need signed note for Sandoval visit before we can bill
**From:** coding@painmedpa.com
**To:** dr.whitmore@painmedpa.com
**Body:**
Dr. Whitmore,

We're unable to submit the claim for K. Sandoval's 06/20 procedure because the visit note is still showing as unsigned in the EHR. The claim has been on hold for 5 days now and we're approaching the timely filing risk window for this payer.

Could you sign off on it today if possible? Happy to walk over a printed copy if that's easier.

Thanks,
Coding Team

---

## Insurance Follow-up

### 19. Follow-up on unpaid claim after 60 days
**Subject:** Second Follow-Up — Claim #CLM-88213 Still Unpaid (60+ Days)
**From:** billing@painmedpa.com
**To:** provider.relations@meridianhealthplans.com
**Body:**
Hello,

This is our second follow-up regarding claim #CLM-88213 (patient J. Alvarez, DOS 05/12/2026), originally submitted 05/14/2026. It remains unpaid with no denial or request for information on file at our end.

Per our provider agreement, claims are expected to be adjudicated within 45 days. Please escalate this claim and provide a resolution date, or advise if it was lost in processing and needs resubmission.

PainMed Physicians Group
Billing Department

---

### 20. Payer escalation response
**Subject:** RE: Second Follow-Up — Claim #CLM-88213
**From:** provider.relations@meridianhealthplans.com
**To:** billing@painmedpa.com
**Body:**
Thank you for reaching out. We've escalated claim #CLM-88213 to our claims resolution team due to the delay. This appears to have been stuck in a manual pricing review queue.

We expect adjudication within 5 business days. We'll follow up directly once it's finalized. We apologize for the delay.

Meridian Health Plans
Provider Relations

---

### 21. Appeal submission follow-up
**Subject:** Confirming Receipt of Appeal — Claim #CLM-90144
**From:** billing@painmedpa.com
**To:** appeals@continentalcareins.com
**Body:**
Hello,

We submitted a formal appeal with supporting documentation for claim #CLM-90144 on 06/05/2026 via certified mail and also faxed a copy to (555) 019-2277. Could you confirm receipt and provide an appeal reference number?

Thank you,
PainMed Physicians Group
Billing Department

---

## Appointment Scheduling

### 22. Patient requesting reschedule
**Subject:** Need to reschedule my Thursday appointment
**From:** m.reyes.patient@outlook.com
**To:** scheduling@painmedpa.com
**Body:**
Hi,

I have an appointment this Thursday at 2:00pm with Dr. Whitmore but something came up at work and I won't be able to make it. Is there any availability next week instead, ideally in the afternoon?

Thanks,
Marcus Reyes

---

### 23. New patient scheduling request tied to referral
**Subject:** Please schedule new referral patient — T. Blackwood
**From:** referrals@painmedpa.com
**To:** scheduling@painmedpa.com
**Body:**
Hi,

We received a referral for a new patient, T. Blackwood, for chronic low back pain evaluation. Referral and imaging are already in the chart. Could you reach out to schedule an initial consult with Dr. Okafor within the next 2 weeks and confirm insurance/authorization isn't needed for an eval visit?

Thanks,
Referral Coordination

---

## Billing Questions

### 24. Patient disputing a bill amount
**Subject:** Question about my bill — amount seems too high
**From:** d.whitfield.patient@yahoo.com
**To:** billing@painmedpa.com
**Body:**
Hello,

I received a statement for $340 for my visit on 05/20/2026, but I thought my insurance was supposed to cover most of this since I met my deductible earlier this year. Can someone explain how this balance was calculated and whether my insurance has already processed this claim?

Thank you,
Diane Whitfield

---

### 25. Employer/HR benefits question forwarded to billing
**Subject:** FW: Employee asking about pain management billing codes
**From:** hr@statelinemanufacturing.com
**To:** billing@painmedpa.com
**Body:**
Hi,

One of our employees came to HR asking why their FSA claim for a recent visit to your office was denied by our FSA administrator. They mentioned the billed procedure code might have been entered incorrectly. Could someone from your billing team reach out directly to the patient (contact info below) to clarify the codes used?

Thanks,
Stateline Manufacturing — HR Benefits

---

### 26. Itemized statement request
**Subject:** Requesting an itemized bill for insurance reimbursement
**From:** t.harmon.patient@gmail.com
**To:** billing@painmedpa.com
**Body:**
Hello,

My out-of-network insurance requires an itemized statement (with CPT codes and charges per line) to process my reimbursement claim, rather than just the summary balance statement I received. Could you send me an itemized version for my 05/22/2026 visit?

Thank you,
Thomas Harmon

---

## Revenue Reports

### 27. Monthly revenue summary request
**Subject:** Need May revenue + collections summary by end of week
**From:** priya.desai@painmedpa.com
**To:** reporting@painmedpa.com
**Body:**
Hi,

Dr. Whitmore is asking for the May revenue cycle summary before Friday's partner meeting — total charges, total collections, adjustment %, and days in A/R by payer. Last month's format is fine, just update the numbers.

Also, if aging over 90 days jumped compared to April, flag which payers are driving it.

Thanks,
Priya Desai
Billing Supervisor

---

### 28. Denial rate trend report
**Subject:** Q2 Denial Rate Report — Draft for Review
**From:** reporting@painmedpa.com
**To:** priya.desai@painmedpa.com
**Body:**
Hi Priya,

Attached is the draft Q2 denial rate report. Highlights:

- Overall denial rate: 8.4% (up from 6.9% in Q1)
- Top denial reason: CO-50 (medical necessity), largely concentrated in RFA and epidural procedures
- Continental Care Insurance accounts for 41% of all denials this quarter

Let me know if you'd like this broken down further by rendering provider before it goes to leadership.

Reporting Team

---

## Vendor Requests

### 29. Clearinghouse renewal notice
**Subject:** Contract Renewal Notice — ClaimLink Exchange Services
**From:** accounts@claimlinkexchange.com
**To:** operations@painmedpa.com
**Body:**
Dear Valued Client,

Your current service agreement with ClaimLink Exchange for electronic claims submission and ERA retrieval is set to expire on 07/31/2026. Please review the attached renewal terms and updated pricing schedule.

To avoid a lapse in claim transmission services, please sign and return the renewal agreement, or contact your account representative to discuss alternate terms, no later than 07/15/2026.

ClaimLink Exchange
Client Accounts Team

---

### 30. Software vendor support request
**Subject:** Support Ticket #SV-40921 — Reporting module export error
**From:** support@brightledgerhealthtech.com
**To:** operations@painmedpa.com
**Body:**
Hello,

Thanks for reporting the issue with the practice management reporting module failing to export A/R aging reports to CSV. We've reproduced the error on our end and identified it as related to a recent update.

A hotfix is scheduled for deployment this weekend. In the meantime, you can export to PDF as a workaround, or contact us directly if this is blocking an urgent reporting deadline.

Best regards,
BrightLedger Health Tech
Client Support
