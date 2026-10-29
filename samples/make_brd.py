"""Generate samples/checkout_brd.pdf — a SYNTHETIC BRD for a fictional company.

Deliberately omits idempotency, checkout timeouts, wallet concurrency locks,
refund flow and data retention so the agent can detect them as gaps.

Usage: python samples/make_brd.py
"""
from pathlib import Path

import pymupdf

OUT_PATH = Path(__file__).resolve().parent / "checkout_brd.pdf"

CSS = """
body { font-family: sans-serif; font-size: 10.5pt; line-height: 1.4; }
h1 { font-size: 18pt; margin-bottom: 4pt; }
h2 { font-size: 13pt; margin-top: 14pt; }
h3 { font-size: 11pt; margin-top: 8pt; }
p.note { font-size: 9pt; color: #666666; }
table { border-collapse: collapse; }
td, th { border: 1px solid #999999; padding: 3pt; font-size: 9.5pt; }
"""

HTML = """
<h1>Business Requirements Document</h1>
<p><b>Project:</b> E-Commerce One-Click Checkout &amp; Wallet<br/>
<b>Company:</b> Lumenfield Home Goods Ltd (fictional)<br/>
<b>Version:</b> 0.9 (draft for architecture review)</p>
<p class="note">SYNTHETIC DOCUMENT — created for a hackathon demo. All names, figures and systems are fictional.</p>

<h2>1. Introduction</h2>
<h3>1.1 Purpose</h3>
<p>This document describes the business requirements for a faster checkout experience and a stored-value
wallet on the Lumenfield online store. It is intended for product, engineering and architecture teams
who will estimate and design the solution.</p>
<h3>1.2 Background</h3>
<p>Lumenfield sells furniture, lighting and home accessories online in the UK and EU. Today, customers
must re-enter delivery and card details on every order. Analytics show that 68% of mobile sessions that
reach the payment page do not complete the purchase. Customer interviews highlight the length of the
checkout form and the lack of a quick way to pay as the main frustrations.</p>
<h3>1.3 Scope</h3>
<p>In scope: one-click checkout for signed-in customers, saved payment cards, a Lumenfield Wallet that
customers can top up and spend, order confirmation notifications, and an operations view of wallet
transactions. The marketplace for third-party sellers and in-store payments are not part of this release.</p>
<h3>1.4 Stakeholders</h3>
<table>
<tr><th>Role</th><th>Interest</th></tr>
<tr><td>Head of Digital Commerce (sponsor)</td><td>Conversion rate and revenue growth</td></tr>
<tr><td>Customer Operations</td><td>Handling wallet queries and order issues</td></tr>
<tr><td>Finance</td><td>Wallet balances and payment settlement</td></tr>
<tr><td>Information Security</td><td>Protection of customer and payment data</td></tr>
<tr><td>Customers</td><td>Fast, trustworthy checkout</td></tr>
</table>

<h2>2. Business Goals</h2>
<h3>2.1 Increase conversion</h3>
<p>Raise mobile checkout conversion from 32% to 45% within six months of launch.</p>
<h3>2.2 Grow repeat purchases</h3>
<p>Increase the share of orders from returning customers from 28% to 40% by making repeat purchases effortless.</p>
<h3>2.3 Introduce a wallet</h3>
<p>Launch the Lumenfield Wallet so that customers can hold a balance (top-ups, promotional credit and
gift card redemptions) and spend it at checkout, alone or combined with a card.</p>

<h2>3. Functional Requirements</h2>
<h3>3.1 One-click checkout</h3>
<p>FR-1. A signed-in customer with a default delivery address and a default payment method shall see a
"Buy now" button on product pages and in the basket.</p>
<p>FR-2. Selecting "Buy now" shall place the order immediately using the default address, default delivery
option and default payment method, and show the order confirmation page.</p>
<p>FR-3. The customer shall be able to change the default address, delivery option and payment method from
their account page.</p>
<p>FR-4. One-click checkout shall be available on web (desktop and mobile browsers).</p>
<h3>3.2 Saved payment cards</h3>
<p>FR-5. During a normal checkout the customer can tick "Remember this card for faster checkout".</p>
<p>FR-6. Saved cards shall be shown with card brand, last four digits and expiry date. Customers can add,
remove and choose a default card.</p>
<p>FR-7. Payments shall be authorised and captured through the payment gateway, PayBridge (fictional),
which also performs Strong Customer Authentication when the card issuer requires it.</p>
<h3>3.3 Lumenfield Wallet</h3>
<p>FR-8. Each customer account has one wallet with a balance in GBP or EUR, depending on the store region.</p>
<p>FR-9. Customers can top up the wallet by card in amounts between 10 and 500 per top-up.</p>
<p>FR-10. At checkout, the customer can pay fully from the wallet, or use the wallet balance first and pay
the remainder by card (split payment).</p>
<p>FR-11. Promotional credit from marketing campaigns and gift card codes can be added to the wallet.</p>
<p>FR-12. The customer can view wallet history: top-ups, payments, promotional credit and gift card redemptions.</p>
<h3>3.4 Notifications</h3>
<p>FR-13. The customer receives an order confirmation e-mail and, where opted in, an SMS.</p>
<p>FR-14. The customer receives an e-mail whenever the wallet is topped up or used.</p>
<h3>3.5 Operations</h3>
<p>FR-15. Customer Operations staff can search wallets by customer e-mail and view the transaction history.</p>
<p>FR-16. Finance receives a daily report of total wallet balances, top-ups and wallet spend.</p>

<h2>4. Non-Functional Requirements</h2>
<h3>4.1 Performance</h3>
<p>NFR-1. The order confirmation page shall appear within 2 seconds for 95% of one-click orders.</p>
<p>NFR-2. The platform shall support 300 orders per minute during seasonal sales events.</p>
<h3>4.2 Availability</h3>
<p>NFR-3. Checkout and wallet services shall be available 99.9% of the time, measured monthly.</p>
<h3>4.3 Security</h3>
<p>NFR-4. Customers must be signed in to use one-click checkout or the wallet.</p>
<p>NFR-5. Staff access to the operations view shall require single sign-on with the company identity provider.</p>
<h3>4.4 Usability and accessibility</h3>
<p>NFR-6. Checkout pages shall meet WCAG 2.1 AA.</p>

<h2>5. Data Requirements</h2>
<p>DR-1. The system stores customer profile data: name, e-mail, phone number, delivery addresses and
order history.</p>
<p>DR-2. The system stores saved payment card details so that one-click checkout does not require
the customer to re-enter them.</p>
<p>DR-3. The system stores the wallet balance and every wallet transaction.</p>

<h2>6. Integrations</h2>
<p>INT-1. PayBridge payment gateway (fictional) for card authorisation, capture and Strong Customer Authentication.</p>
<p>INT-2. Existing Order Management System for order fulfilment.</p>
<p>INT-3. Existing e-mail and SMS notification service.</p>
<p>INT-4. Finance reporting data warehouse (daily batch).</p>

<h2>7. Assumptions and Constraints</h2>
<p>A-1. Customers already have accounts; registration and sign-in are unchanged.</p>
<p>A-2. Delivery options and prices are provided by the existing Order Management System.</p>
<p>C-1. The solution must use the company's approved technology stack.</p>
<p>C-2. Target launch is before the autumn sales season.</p>

<h2>8. Success Metrics</h2>
<table>
<tr><th>Metric</th><th>Baseline</th><th>Target</th></tr>
<tr><td>Mobile checkout conversion</td><td>32%</td><td>45%</td></tr>
<tr><td>Orders from returning customers</td><td>28%</td><td>40%</td></tr>
<tr><td>Customers with a funded wallet</td><td>0%</td><td>15%</td></tr>
<tr><td>Average checkout time (returning customer)</td><td>95 s</td><td>under 10 s</td></tr>
</table>
"""


def main() -> None:
    """Render the BRD HTML to a multi-page A4 PDF."""
    story = pymupdf.Story(html=HTML, user_css=CSS)
    writer = pymupdf.DocumentWriter(str(OUT_PATH))
    mediabox = pymupdf.paper_rect("a4")
    where = mediabox + (60, 60, -60, -60)
    more = True
    while more:
        device = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(device)
        writer.end_page()
    writer.close()

    with pymupdf.open(OUT_PATH) as doc:
        print(f"Wrote {OUT_PATH} ({doc.page_count} pages)")


if __name__ == "__main__":
    main()
