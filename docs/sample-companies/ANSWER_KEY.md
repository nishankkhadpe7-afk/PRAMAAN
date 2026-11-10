# Answer key: what Neelgiri Lifestyle is hiding

Spoilers. Try `.\START_PRAMAAN.bat company hiding` and look for these yourself first.

**The scheme:** to show higher sales at year end (say, for a bank loan), Neelgiri books large sales to Vardhan Distributors, a shell customer that shares a director with Neelgiri. The goods never move, the sales are kept out of the GST return so no tax is paid on them, and most are reversed by credit notes once the year has closed. Money is cycled through Om Sai Trading Company so the "sales" look paid. Around that, smaller things are hidden too.

| # | What is hidden | Records involved | Found by | Where to look in PRAMAAN |
|---|---|---|---|---|
| 1 | Year-end sales to a related shell customer | NLP/25-26/1307 to 1315: 9 invoices to Vardhan Distributors, 24–31 Mar 2026, ₹71.6 lakh against a usual ₹56,000 a month | **T08** period-end concentration; **T06** no transport documents; **T10** the 9 bills also look like one split order | Findings: T08, T06 (GAP), T10 |
| 2 | Shell sales kept out of the GST return | The same 9 invoices are in the books but not in March GSTR-1 | GSTR-1 import + **T00** | Registers: GSTR-1 03/2026 shows 9 "in books, not in return" |
| 3 | Year-end sales reversed after the year closed | NLP-CN901 to CN907: credit notes on 8–26 Apr 2026 fully reversing 7 shell invoices | **T09** post-period credit notes | Findings: T09 |
| 4 | Sales to a connected party hidden from the auditor's register | NLP/25-26/1316 to 1318 to Om Sai Trading Company: in the books, missing from the register. Its GSTIN check digit is also wrong | **T00** (SYSTEM_ONLY); GSTR-1 import warns on the GSTIN | Registers: sales register; the GSTR-1 upload warnings |
| 5 | An amount changed in the register | NLP/25-26/0736 shows ₹25,000 less in the register than in the books | **T00** (FIELD_DIFF) | Registers: sales register |
| 6 | Sales under-reported in GST | NLP/25-26/1091 and 1099 filed in February GSTR-1 at 60% of their taxable value | **T15**; GSTR-1 import (FIELD_DIFF) | Findings: T15; Registers: GSTR-1 02/2026 |
| 7 | One order split to avoid the approval limit | NLP/25-26/1319 and 1320: same buyer and product, two days apart, about ₹7.9 lakh each, together over the ₹15 lakh director-approval limit | **T10** | Findings: T10 |
| 8 | Transport records that can't be true | 0676: Surat to a far city in 7 hours. 0676 and 0677: the same truck on two trips at once. 0588: load above the truck's capacity. 0890: goods delivered in a different state from the buyer's | **T11** (P1 speed, P2 vehicle overlap, P3 load, P5 delivery state) | Findings: T11 |
| 9 | Contract customer billed below the agreed price | 1005, 1006, 1008: 12% under the price list. NLP-PROMO-02: a discount scheme with no approval | **T14** | Findings: T14 |
| 10 | E-invoice problems | 0618: changed after its QR code was signed. 0619: registered 25 days after its date. 0620 to 0623: B2B invoices with no IRN | **T13** | Findings: T13 (INCONSISTENT, timing risk, UNAVAILABLE) |
| 11 | Revenue entered by hand with no invoice | NLP-JV-ADJ-01: ₹6,50,000 "year-end sales adjustment" on 31 Mar 2026 | **T05** | Findings: T05 |
| 12 | Hidden relationship and circular trading | Vardhan shares a director with Neelgiri; money and goods loop Neelgiri → Vardhan → Om Sai → Neelgiri | **T02** (candidate links and a cycle) | Findings: T02 |

**Not checked automatically:** the bank statement shows ₹15 lakh arriving from Vardhan on 30 March, going straight out to Om Sai the same day, and ₹14.8 lakh coming back from Om Sai on 3 April. PRAMAAN imports the statement but has no automatic bank check yet. You can ask the AI assistant to look at it, or read it yourself.

What each finding means is a **signal for review**, never a conclusion. In real life, each of these would need evidence and a human decision, and that is exactly the workflow PRAMAAN records.
