import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Image as RLImage,
    Table,
    TableStyle,
    PageBreak,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

from backend.config import DEMO_DIR

os.makedirs(DEMO_DIR, exist_ok=True)
TEMP_IMG_DIR = os.path.join(DEMO_DIR, "temp_assets")
os.makedirs(TEMP_IMG_DIR, exist_ok=True)


def create_logo_image() -> str:
    path = os.path.join(TEMP_IMG_DIR, "acme_logo.png")
    img = Image.new("RGBA", (400, 150), color=(255, 255, 255, 255))
    draw = ImageDraw.Draw(img)
    # Draw green leaf/organic icon
    draw.ellipse([20, 25, 120, 125], fill=(34, 139, 34))
    draw.ellipse([45, 45, 95, 105], fill=(255, 255, 255))
    draw.polygon([(70, 30), (110, 70), (70, 110), (30, 70)], fill=(46, 204, 113))
    # Draw text
    draw.text((140, 40), "ACME FOODS", fill=(26, 82, 118))
    draw.text((142, 85), "Pristine Nutrition Since 2012", fill=(100, 110, 120))
    img.save(path)
    return path


def create_portrait_image(name: str, color_tuple) -> str:
    path = os.path.join(TEMP_IMG_DIR, f"{name.lower().replace(' ', '_')}.png")
    img = Image.new("RGB", (140, 140), color=color_tuple)
    draw = ImageDraw.Draw(img)
    draw.ellipse([35, 20, 105, 80], fill=(240, 240, 240))
    draw.ellipse([15, 85, 125, 150], fill=(240, 240, 240))
    draw.text((25, 115), name.split()[0], fill=(20, 20, 20))
    img.save(path)
    return path


def create_product_image(product_name: str, color_hex: str) -> str:
    path = os.path.join(TEMP_IMG_DIR, f"{product_name.lower().replace(' ', '_')}.png")
    fig, ax = plt.subplots(figsize=(2.5, 2), dpi=100)
    ax.set_facecolor("#f9f9f9")
    ax.bar([1], [8], color=color_hex, width=0.6, edgecolor="#333", linewidth=1.5)
    ax.set_title(product_name, fontsize=10, weight="bold")
    ax.axis("off")
    plt.tight_layout()
    plt.savefig(path, bbox_inches="tight", dpi=100)
    plt.close()
    return path


def create_org_chart_image() -> str:
    path = os.path.join(TEMP_IMG_DIR, "acme_org_chart.png")
    fig, ax = plt.subplots(figsize=(7, 4.5), dpi=130)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 7)
    ax.axis("off")

    # Boxes: [x, y, w, h, text, color]
    boxes = [
        (3.8, 5.5, 2.4, 1.0, "Dr. Evelyn Vance\nChief Executive Officer", "#1f77b4"),
        (0.6, 3.5, 2.2, 0.9, "Marcus Brody\nVP of Operations", "#2ca02c"),
        (3.9, 3.5, 2.2, 0.9, "Dr. Clara O'Connor\nHead of R&D & Quality", "#ff7f0e"),
        (7.2, 3.5, 2.2, 0.9, "Rajesh Kothari\nVP of Global Sales", "#9467bd"),
        (0.6, 1.5, 2.2, 0.8, "Supply Chain &\nPackaging Teams", "#e5e5e5"),
        (3.9, 1.5, 2.2, 0.8, "Food Safety &\nFormulation Labs", "#e5e5e5"),
        (7.2, 1.5, 2.2, 0.8, "Retail Partners &\nDirect Distribution", "#e5e5e5"),
    ]

    from matplotlib.patches import FancyBboxPatch
    for x, y, w, h, text, color in boxes:
        is_exec = color != "#e5e5e5"
        rect = FancyBboxPatch(
            (x, y), w, h,
            boxstyle="round,pad=0.15",
            facecolor=color,
            edgecolor="#111",
            linewidth=1.5,
        )
        ax.add_patch(rect)
        ax.text(
            x + w / 2, y + h / 2, text,
            ha="center", va="center",
            fontsize=8.5 if not is_exec else 9.5,
            weight="bold" if is_exec else "normal",
            color="white" if is_exec else "#222",
        )

    # Connecting lines
    ax.plot([5.0, 5.0], [5.5, 4.7], color="#333", lw=2)
    ax.plot([1.7, 8.3], [4.7, 4.7], color="#333", lw=2)
    ax.plot([1.7, 1.7], [4.7, 4.4], color="#333", lw=2)
    ax.plot([5.0, 5.0], [4.7, 4.4], color="#333", lw=2)
    ax.plot([8.3, 8.3], [4.7, 4.4], color="#333", lw=2)

    ax.plot([1.7, 1.7], [3.5, 2.3], color="#666", lw=1.5, ls="--")
    ax.plot([5.0, 5.0], [3.5, 2.3], color="#666", lw=1.5, ls="--")
    ax.plot([8.3, 8.3], [3.5, 2.3], color="#666", lw=1.5, ls="--")

    plt.title("Acme Foods Pvt Ltd - Executive Organization Structure (2026)", fontsize=11, weight="bold", pad=12)
    plt.tight_layout()
    plt.savefig(path, bbox_inches="tight", dpi=130)
    plt.close()
    return path


def create_sales_chart_image() -> str:
    path = os.path.join(TEMP_IMG_DIR, "acme_sales_chart.png")
    fig, ax = plt.subplots(figsize=(6, 3.2), dpi=120)
    quarters = ["Q1-2025", "Q2-2025", "Q3-2025", "Q4-2025", "Q1-2026"]
    revenue = [18.5, 22.1, 27.4, 34.0, 39.8]
    ax.plot(quarters, revenue, marker="o", color="#27ae60", linewidth=3, markersize=8)
    for q, r in zip(quarters, revenue):
        ax.annotate(f"${r}M", (q, r + 1.0), ha="center", weight="bold", color="#196f3d", fontsize=9)
    ax.set_ylim(10, 45)
    ax.set_ylabel("Revenue ($ Millions)")
    ax.set_title("Quarterly Revenue Growth (Organic & Specialty Segment)", fontsize=10, weight="bold")
    ax.grid(True, linestyle=":", alpha=0.6)
    plt.tight_layout()
    plt.savefig(path, bbox_inches="tight", dpi=120)
    plt.close()
    return path


def generate_demo_pdf():
    pdf_path = os.path.join(DEMO_DIR, "Acme_Foods_Overview.pdf")
    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=letter,
        leftMargin=40,
        rightMargin=40,
        topMargin=40,
        bottomMargin=40,
    )
    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        "CoverTitle",
        parent=styles["Normal"],
        fontSize=24,
        leading=28,
        textColor=colors.HexColor("#1A5276"),
        alignment=1,
        fontName="Helvetica-Bold",
    )
    subtitle_style = ParagraphStyle(
        "CoverSubtitle",
        parent=styles["Normal"],
        fontSize=13,
        leading=16,
        textColor=colors.HexColor("#5D6D7E"),
        alignment=1,
    )
    h1_style = ParagraphStyle(
        "CustomH1",
        parent=styles["Heading1"],
        fontSize=16,
        leading=20,
        textColor=colors.HexColor("#1A5276"),
        spaceAfter=10,
    )
    body_style = ParagraphStyle(
        "CustomBody",
        parent=styles["Normal"],
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#2C3E50"),
        spaceAfter=8,
    )
    caption_style = ParagraphStyle(
        "Caption",
        parent=styles["Normal"],
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#7F8C8D"),
        alignment=1,
        spaceAfter=12,
    )

    logo_path = create_logo_image()
    ceo_photo = create_portrait_image("Evelyn Vance", (41, 128, 185))
    coo_photo = create_portrait_image("Marcus Brody", (39, 174, 96))
    prod1_img = create_product_image("Organic Oat Crunch", "#F39C12")
    prod2_img = create_product_image("Himalayan Apple Chips", "#E74C3C")
    prod3_img = create_product_image("Artisan Almond Butter", "#8E44AD")
    prod4_img = create_product_image("Sparkling Berry Tonic", "#3498DB")
    org_chart = create_org_chart_image()
    sales_chart = create_sales_chart_image()

    elements = []

    # ================= PAGE 1: COVER & LOGO =================
    elements.append(Spacer(1, 40))
    elements.append(RLImage(logo_path, width=320, height=120))
    elements.append(Spacer(1, 50))
    elements.append(Paragraph("Acme Foods Pvt Ltd", title_style))
    elements.append(Spacer(1, 15))
    elements.append(Paragraph("Enterprise Knowledge Base & Operational Handbook (2026)", subtitle_style))
    elements.append(Spacer(1, 60))
    cover_table = Table([
        ["Document ID:", "ACME-CORP-DOC-2026-V3"],
        ["Publication Date:", "January 15, 2026"],
        ["Classification:", "Company Confidential / Internal Distribution"],
        ["Corporate Headquarters:", "450 Organic Parkway, Suite 800, Boulder, CO 80301"],
        ["Contact Hotline:", "+1 (800) 555-ACME | info@acmefoods.com"],
    ], colWidths=[160, 320])
    cover_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#1A5276")),
        ("TEXTCOLOR", (1, 0), (1, -1), colors.HexColor("#333333")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(cover_table)
    elements.append(PageBreak())

    # ================= PAGE 2: LEADERSHIP & CONTACTS =================
    elements.append(Paragraph("1. Executive Leadership & Governance", h1_style))
    elements.append(Paragraph(
        "Acme Foods is steered by veteran food science and supply chain visionaries committed to sustainable agriculture, zero-compromise ingredient purity, and transparent consumer packaging.",
        body_style,
    ))
    elements.append(Spacer(1, 10))

    exec_table = Table([
        [
            RLImage(ceo_photo, width=90, height=90),
            Paragraph("<b>Dr. Evelyn Vance</b><br/><b>Title:</b> Chief Executive Officer (CEO)<br/><b>Email:</b> evelyn.vance@acmefoods.com<br/><b>Focus:</b> Corporate Strategy, ESG Sustainability, and Capital Allocation.<br/><b>Bio:</b> Ph.D. in Food Biochemistry from Cornell with 18 years in organic FMCG.", body_style),
        ],
        [
            RLImage(coo_photo, width=90, height=90),
            Paragraph("<b>Marcus Brody</b><br/><b>Title:</b> VP of Global Operations<br/><b>Email:</b> marcus.brody@acmefoods.com<br/><b>Focus:</b> Cold Chain Logistics, Zero-Waste Warehousing, and Farm Partnerships.<br/><b>Bio:</b> Former logistics director overseeing 14 processing plants nationwide.", body_style),
        ],
    ], colWidths=[110, 370])
    exec_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
    ]))
    elements.append(exec_table)
    elements.append(Paragraph("Figure 1.1: Executive Leadership Team of Acme Foods Pvt Ltd", caption_style))
    elements.append(Paragraph(
        "<b>Ethics & Compliance Officer:</b> Sarah Jenkins (sarah.jenkins@acmefoods.com)<br/>"
        "<b>Whistleblower Hotline:</b> Available 24/7 with complete anonymity at 1-888-SAFE-FOOD.",
        body_style,
    ))
    elements.append(PageBreak())

    # ================= PAGE 3: PRODUCTS & ALLERGENS =================
    elements.append(Paragraph("2. Core Product Portfolio & Allergen Declarations", h1_style))
    elements.append(Paragraph(
        "All Acme Foods products are manufactured in audited SQF Level 3 certified facilities. Each production lot undergoes third-party chromatography testing for heavy metals and chemical residue.",
        body_style,
    ))
    elements.append(Spacer(1, 6))

    prod_grid = Table([
        [
            RLImage(prod1_img, width=110, height=80),
            Paragraph("<b>Organic Oat Crunch (SKU: OAT-101)</b><br/><b>Price:</b> $4.99 (12 oz)<br/><b>Ingredients:</b> Rolled organic oats, raw wildflower honey, cold-pressed sunflower oil, sea salt.<br/><b>Allergen Notice:</b> Gluten-Free certified (oats). Processed in a tree-nut free line.", body_style),
        ],
        [
            RLImage(prod2_img, width=110, height=80),
            Paragraph("<b>Himalayan Apple Chips (SKU: APP-204)</b><br/><b>Price:</b> $3.79 (3.5 oz)<br/><b>Ingredients:</b> Freeze-dried handpicked Himalayan crisp apples, Ceylon cinnamon.<br/><b>Allergen Notice:</b> 100% Free of top 9 allergens. Vegan and Non-GMO Project verified.", body_style),
        ],
        [
            RLImage(prod3_img, width=110, height=80),
            Paragraph("<b>Artisan Almond Butter (SKU: NUT-305)</b><br/><b>Price:</b> $8.49 (16 oz)<br/><b>Ingredients:</b> Dry roasted California almonds, pink Himalayan crystal salt.<br/><b>Allergen Notice:</b> Contains Almonds (Tree Nuts). Manufactured on dedicated almond lines.", body_style),
        ],
        [
            RLImage(prod4_img, width=110, height=80),
            Paragraph("<b>Sparkling Berry Tonic (SKU: BEV-412)</b><br/><b>Price:</b> $2.99 (12 fl oz)<br/><b>Ingredients:</b> Sparkling mountain spring water, cold-pressed blackberry extract, prebiotic agave fiber.<br/><b>Allergen Notice:</b> Allergen-free. Kosher and Halal certified.", body_style),
        ],
    ], colWidths=[120, 360])
    prod_grid.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(prod_grid)
    elements.append(Paragraph("Figure 2.1: Key Retail Products & Packaging Specifications", caption_style))
    elements.append(PageBreak())

    # ================= PAGE 4: ORG CHART =================
    elements.append(Paragraph("3. Company Organizational Structure", h1_style))
    elements.append(Paragraph(
        "Acme Foods operates a matrix governance model connecting R&D, Farm Partnerships, Processing, and Global Distribution under executive supervisory oversight.",
        body_style,
    ))
    elements.append(Spacer(1, 10))
    elements.append(RLImage(org_chart, width=480, height=270))
    elements.append(Paragraph("Figure 3.1: Organizational Hierarchy & Supervisory Reporting Lines", caption_style))
    elements.append(Spacer(1, 10))
    elements.append(Paragraph(
        "<b>Supervisory Flow:</b><br/>"
        "• Dr. Evelyn Vance (CEO) directly supervises Operations, R&D, and Global Sales.<br/>"
        "• Marcus Brody (VP Ops) leads Supply Chain logistics and packaging automation.<br/>"
        "• Dr. Clara O'Connor heads Quality Assurance and microbiological formulation labs.<br/>"
        "• Rajesh Kothari oversees institutional supermarket accounts and direct-to-consumer digital channels.",
        body_style,
    ))
    elements.append(PageBreak())

    # ================= PAGE 5: HR POLICIES =================
    elements.append(Paragraph("4. Human Resources & Workplace Policies", h1_style))
    elements.append(Paragraph(
        "Acme Foods promotes a healthy, inclusive, and performance-driven environment. Below are the definitive guidelines governing employment at Acme Foods Pvt Ltd.",
        body_style,
    ))
    elements.append(Spacer(1, 6))

    hr_table = Table([
        ["Policy Domain", "Official Guideline & Entitlements"],
        [
            "Remote Work & Hybrid",
            "Employees in corporate and software functions are entitled to up to 3 days per week remote work (Tuesday & Thursday mandatory in-office collaboration days). Plant operators and QA lab technicians follow on-site rotational schedules with 15% shift differentials.",
        ],
        [
            "Paid Time Off (PTO)",
            "Standard full-time staff receive 22 days paid annual leave, 10 paid federal holidays, and 8 wellness days. Unused PTO up to 7 days carries over into Q1 of the subsequent calendar year.",
        ],
        [
            "Health & Wellness",
            "Comprehensive medical, dental, and vision insurance covered at 90% by Acme Foods. In addition, an annual $800 wellness stipend is provided for gym memberships, CSA farm shares, or ergonomics equipment.",
        ],
        [
            "Parental Leave",
            "16 weeks of 100% paid parental leave for primary caregivers and 8 weeks for secondary caregivers, applicable for birth, adoption, or foster placement.",
        ],
        [
            "Anti-Harassment",
            "Zero tolerance for discrimination, harassment, or retaliation. Complaints are handled by the Chief People Officer with investigation concluded within 5 business days.",
        ],
    ], colWidths=[140, 340])
    hr_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1A5276")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#BDC3C7")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    elements.append(hr_table)
    elements.append(Spacer(1, 10))
    elements.append(Paragraph(
        "<b>Overtime & Travel:</b> Non-exempt personnel working over 40 hours per week receive 1.5x hourly pay. Business travel expenses must be submitted via Concur within 14 days of completion.",
        body_style,
    ))
    elements.append(PageBreak())

    # ================= PAGE 6: SALES & CONTACTS =================
    elements.append(Paragraph("5. Sales Performance, Distribution & Facility Locations", h1_style))
    elements.append(Paragraph(
        "Fiscal Year 2025 closed with record revenue of $102M across retail grocery and organic wholesale partnerships. Q1-2026 performance continues the upward trajectory driven by the beverage segment.",
        body_style,
    ))
    elements.append(Spacer(1, 6))
    elements.append(RLImage(sales_chart, width=460, height=210))
    elements.append(Paragraph("Figure 5.1: 2025-2026 Regional Revenue Growth Trajectory", caption_style))
    elements.append(Spacer(1, 6))

    loc_table = Table([
        ["Facility Name", "Function", "Location & Direct Contact"],
        ["Rocky Mountain HQ", "Corporate & Labs", "Boulder, CO | +1 (303) 555-0192"],
        ["Midwest Logistics Center", "Packaging & Central Distribution", "Omaha, NE | +1 (402) 555-0144"],
        ["Pacific Cold Storage", "West Coast Logistics", "Fresno, CA | +1 (559) 555-0188"],
    ], colWidths=[140, 140, 200])
    loc_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#27AE60")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#BDC3C7")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(loc_table)

    doc.build(elements)
    print(f"Created PDF: {pdf_path}")
    return pdf_path


def generate_demo_docx():
    docx_path = os.path.join(DEMO_DIR, "Acme_Foods_HR_Policy.docx")
    doc = docx.Document()

    # Title
    p_title = doc.add_paragraph()
    run = p_title.add_run("Acme Foods Pvt Ltd - Comprehensive HR & Employment Policy")
    run.font.size = Pt(20)
    run.font.bold = True
    run.font.color.rgb = RGBColor(26, 82, 118)

    doc.add_paragraph("Document Revision: 2026.1 | Applicable to All Global Employees & Contractors")

    # Section 1
    doc.add_heading("Section 1: Working Hours, Remote Flexibility & Attendance", level=1)
    doc.add_paragraph(
        "Acme Foods adopts an agile, results-oriented workplace framework. Core operational collaboration hours are 10:00 AM to 3:00 PM local time. "
        "Employees eligible for remote flexibility may elect to work remotely up to three business days per week upon manager approval. "
        "Mandatory on-site collaboration occurs on Tuesdays and Thursdays to foster cross-functional synergy."
    )

    # Section 2
    doc.add_heading("Section 2: Comprehensive Compensation and Bonus Structure", level=1)
    doc.add_paragraph(
        "Base salaries are benchmarked annually against 75th percentile FMCG food sector standards. Annual performance bonuses are tied to corporate EBITDA milestones and personal OKR evaluations. "
        "Performance reviews occur biannually in June and December."
    )

    table = doc.add_table(rows=1, cols=3)
    hdr_cells = table.rows[0].cells
    hdr_cells[0].text = "Tier"
    hdr_cells[1].text = "Target Annual Bonus"
    hdr_cells[2].text = "Eligibility Criteria"

    data = [
        ("Tier 1: Plant & Warehouse Staff", "8% of base salary", "Zero safety incidents + 95% attendance"),
        ("Tier 2: Professional & Specialist", "15% of base salary", "Departmental OKR achievement >= 90%"),
        ("Tier 3: Executive Leadership", "30% - 50% of base", "Company EBITDA targets + ESG audit rating A"),
    ]
    for tier, bonus, elig in data:
        row_cells = table.add_row().cells
        row_cells[0].text = tier
        row_cells[1].text = bonus
        row_cells[2].text = elig

    # Add embedded image into docx
    logo_path = os.path.join(TEMP_IMG_DIR, "acme_logo.png")
    if os.path.exists(logo_path):
        doc.add_paragraph()
        doc.add_picture(logo_path, width=Inches(3.5))
        caption_p = doc.add_paragraph("Figure 1: Acme Foods Certified Organic Operational Seal")
        caption_p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # Section 3
    doc.add_heading("Section 3: Professional Development & Tuition Reimbursement", level=1)
    doc.add_paragraph(
        "Acme Foods invests in ongoing workforce education. Regular employees who have completed six months of service are eligible for up to $4,500 per year in tuition reimbursement "
        "for accredited degree programs, industry certifications (e.g., HACCP, Six Sigma, CPA), or relevant technical coursework."
    )

    doc.save(docx_path)
    print(f"Created DOCX: {docx_path}")
    return docx_path


def generate_demo_txt():
    txt_path = os.path.join(DEMO_DIR, "Acme_Foods_FAQ.txt")
    content = """===============================================================
ACME FOODS PVT LTD - OFFICIAL CUSTOMER & PARTNER FAQ (2026)
===============================================================

Section 1: Sourcing & Organic Certifications
---------------------------------------------------------------
Q: Where does Acme Foods source its raw agricultural ingredients?
A: 100% of our organic oats are sourced from family-owned cooperatives in Minnesota and Wisconsin. Our almonds are grown in pesticide-free certified organic orchards in the Central Valley of California. Our freeze-dried apples are harvested from high-altitude orchards in Himachal Pradesh.

Q: Are Acme Foods products Non-GMO and USDA Organic certified?
A: Yes, all Acme Foods product lines hold active USDA Organic, Non-GMO Project Verified, and Certified Gluten-Free certifications from the Gluten Intolerance Group (GIG).

---

Section 2: Wholesale Ordering, MOQs and Lead Times
---------------------------------------------------------------
Q: What is the Minimum Order Quantity (MOQ) for retail distributors?
A: For direct store delivery (DSD), the standard MOQ is 50 master cases per SKU. For regional distribution centers, pallet-tier ordering requires a minimum of 2 full pallets (mix-and-match allowed).

Q: What are the typical fulfillment lead times?
A: Standard domestic lead time is 5 to 7 business days from purchase order confirmation. Expedited cold-chain freight is available within 48 hours for an additional 12% surcharge.

---

Section 3: Product Shelf Life, Storage and Recalls
---------------------------------------------------------------
Q: What is the recommended shelf life and storage condition for Acme Foods snacks?
A:
- Organic Oat Crunch: 12 months shelf life when stored at ambient temperature below 75°F (24°C) in a dry pantry.
- Himalayan Apple Chips: 18 months unopened shelf life in moisture-barrier packaging.
- Artisan Almond Butter: 9 months from manufacture. Natural oil separation is normal; stir well before consuming. Refrigeration after opening extends freshness up to 12 months.
- Sparkling Berry Tonic: 14 months unopened in chilled or ambient conditions away from direct sunlight.

Q: What is Acme Foods' historical product recall record?
A: Acme Foods maintains an impeccable safety record with zero Class I or Class II recalls in our 14-year corporate history. Every lot is sealed with a unique QR code allowing consumers to trace the batch back to the harvest farm.

---

Section 4: Sustainability & Carbon Neutral Packaging
---------------------------------------------------------------
Q: How sustainable is Acme Foods' packaging?
A: By 2025, 94% of our packaging by weight is compostable or 100% curbside recyclable. Our snack pouches utilize plant-based polylactic acid (PLA) linings derived from non-food corn starch. Our beverage cans are made of 85% post-consumer recycled aluminum.
"""
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(content.strip())
    print(f"Created TXT: {txt_path}")
    return txt_path


def generate_demo_png():
    png_path = os.path.join(DEMO_DIR, "Acme_Foods_Price_List.png")
    fig, ax = plt.subplots(figsize=(8, 5.5), dpi=150)
    ax.axis("off")

    table_data = [
        ["SKU Code", "Product Description", "Pack Size", "Wholesale Case (12 pk)", "MSRP / Unit"],
        ["OAT-101", "Organic Oat Crunch", "12 oz Pouch", "$38.50", "$4.99"],
        ["OAT-102", "Oat Crunch Honey Almond", "12 oz Pouch", "$42.00", "$5.49"],
        ["APP-204", "Himalayan Apple Chips", "3.5 oz Bag", "$28.00", "$3.79"],
        ["APP-205", "Cinnamon Spiced Apple Chips", "3.5 oz Bag", "$29.50", "$3.99"],
        ["NUT-305", "Artisan Almond Butter (Creamy)", "16 oz Glass Jar", "$68.00", "$8.49"],
        ["NUT-306", "Artisan Almond Butter (Crunchy)", "16 oz Glass Jar", "$68.00", "$8.49"],
        ["BEV-412", "Sparkling Berry Tonic", "12 fl oz Can", "$22.00", "$2.99"],
        ["BEV-415", "Sparkling Ginger Lime Tonic", "12 fl oz Can", "$22.00", "$2.99"],
    ]

    table = ax.table(
        cellText=table_data,
        cellLoc="center",
        loc="center",
        bbox=[0.02, 0.08, 0.96, 0.78],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)

    # Style header row
    for col in range(5):
        cell = table[0, col]
        cell.set_facecolor("#1A5276")
        cell.get_text().set_color("white")
        cell.get_text().set_weight("bold")

    # Alternate row colors
    for row in range(1, len(table_data)):
        color = "#F2F4F4" if row % 2 == 0 else "#FFFFFF"
        for col in range(5):
            table[row, col].set_facecolor(color)

    ax.text(
        0.5, 0.93,
        "ACME FOODS PVT LTD - OFFICIAL 2026 WHOLESALE PRICE LIST",
        fontsize=12,
        weight="bold",
        color="#1A5276",
        ha="center",
    )
    ax.text(
        0.5, 0.88,
        "Effective January 1, 2026 | All prices in USD F.O.B. Boulder, Colorado",
        fontsize=8.5,
        color="#555555",
        ha="center",
    )
    ax.text(
        0.5, 0.02,
        "Terms: Net 30 for qualified distributors. Volume discounts: 5% on 200+ cases, 10% on 500+ cases.",
        fontsize=8,
        color="#777777",
        ha="center",
        style="italic",
    )

    plt.tight_layout()
    plt.savefig(png_path, bbox_inches="tight", dpi=150)
    plt.close()
    print(f"Created PNG: {png_path}")
    return png_path


def generate_all_demo_files():
    print("Generating demo files for Acme Foods Pvt Ltd...")
    pdf = generate_demo_pdf()
    docx_file = generate_demo_docx()
    txt = generate_demo_txt()
    png = generate_demo_png()
    print("\nAll 4 demo files successfully generated in /demo/ directory:")
    print(f"1. PDF:  {pdf}")
    print(f"2. DOCX: {docx_file}")
    print(f"3. TXT:  {txt}")
    print(f"4. PNG:  {png}")


if __name__ == "__main__":
    generate_all_demo_files()
