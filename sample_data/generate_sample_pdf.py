"""Synthetic 5-Page Test PDF Generator for ABC Technologies.

Constructs a structured, multi-page company profile PDF implementing all
factual specifications from Section 7 of the Sixthsense Technologies assignment.
Uses ReportLab to produce clean, multi-page vector PDF output.
"""

from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_PDF_PATH = BASE_DIR / "ABC_Technologies_Profile.pdf"


def generate_pdf(output_path: Path = OUTPUT_PDF_PATH) -> Path:
    """Generates the 5-page ABC Technologies profile PDF."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "PageTitle",
        parent=styles["Heading1"],
        fontSize=20,
        leading=24,
        spaceAfter=14,
        textColor="#1E3A8A",
    )
    subtitle_style = ParagraphStyle(
        "PageSubtitle",
        parent=styles["Heading2"],
        fontSize=13,
        leading=17,
        spaceAfter=10,
        textColor="#2563EB",
    )
    body_style = ParagraphStyle(
        "PageBody",
        parent=styles["Normal"],
        fontSize=10.5,
        leading=15,
        spaceAfter=10,
        textColor="#1F2937",
    )

    story = []

    # ==========================================
    # PAGE 1: Overview & Primary Business Focus
    # ==========================================
    story.append(Paragraph("ABC Technologies - Corporate Overview", title_style))
    story.append(Paragraph("Enterprise Profile and Strategic Mission", subtitle_style))
    story.append(
        Paragraph(
            "ABC Technologies is an established information technology consultancy dedicated to modern "
            "enterprise transformation. Founded to empower businesses with dependable digital infrastructure, "
            "the organization works across commercial sectors to build resilient, high-performance web systems.",
            body_style,
        )
    )
    story.append(
        Paragraph(
            "The company's primary business focus centers on delivering end-to-end digital enablement and "
            "scalable online business solutions. By harmonizing technical precision with client-centric strategy, "
            "ABC Technologies assists modern enterprises in modernizing legacy operational channels into "
            "agile digital ecosystems.",
            body_style,
        )
    )
    story.append(
        Paragraph(
            "Over recent operational cycles, the organization has observed continuous client growth, scaling its "
            "active client portfolio to more than 150 enterprise partners while maintaining an exceptional "
            "ninety-eight percent client retention rate.",
            body_style,
        )
    )
    story.append(PageBreak())

    # ==========================================
    # PAGE 2: Service Portfolio (Test 1 & Test 2)
    # ==========================================
    story.append(Paragraph("Core Service Portfolio", title_style))
    story.append(Paragraph("Comprehensive Commercial Capabilities", subtitle_style))
    story.append(
        Paragraph(
            "ABC Technologies provides four dedicated core capabilities to corporate clients worldwide: "
            "website development, domain registration, email hosting and digital marketing services.",
            body_style,
        )
    )
    story.append(
        Paragraph(
            "Our bespoke website development practice specializes in tailoring interactive enterprise portals, "
            "e-commerce platforms, and customer-facing web environments aligned with organizational branding.",
            body_style,
        )
    )
    story.append(
        Paragraph(
            "Through our corporate domain registration facility, businesses secure and manage critical top-level "
            "domains, automated DNS zone management, and brand protection registries.",
            body_style,
        )
    )
    story.append(
        Paragraph(
            "Our managed email hosting infrastructure guarantees reliable business email solutions featuring "
            "secure encrypted mailboxes, spam filtering, custom corporate domains, and round-the-clock availability.",
            body_style,
        )
    )
    story.append(
        Paragraph(
            "Finally, our digital marketing services orchestrate multi-channel performance campaigns, organic "
            "search visibility programs, and targeted data-driven client acquisition funnels.",
            body_style,
        )
    )
    story.append(PageBreak())

    # ==========================================
    # PAGE 3: Engineering Stack (Test 3)
    # ==========================================
    story.append(Paragraph("Technical Architecture & Engineering Stack", title_style))
    story.append(Paragraph("Frontend and Application Technologies", subtitle_style))
    story.append(
        Paragraph(
            "The engineering division at ABC Technologies upholds rigorous architectural standards across "
            "all development initiatives. Every digital deliverable is crafted following modular and maintainable "
            "software principles.",
            body_style,
        )
    )
    story.append(
        Paragraph(
            "For client-side implementation, its website development team uses HTML5, CSS and JavaScript. "
            "This foundational triad ensures seamless cross-browser rendering, dynamic user interface components, "
            "and accessible semantic layouts across desktop, tablet, and mobile displays.",
            body_style,
        )
    )
    story.append(
        Paragraph(
            "The engineering team enforces strict automated linting and responsive design methodologies. Clean "
            "markup separation ensures that visual presentation, interactive logic, and foundational content "
            "remain decoupled for long-term maintainability.",
            body_style,
        )
    )
    story.append(PageBreak())

    # ==========================================
    # PAGE 4: Process & Leadership (Test 6)
    # ==========================================
    story.append(Paragraph("Operational Framework & Executive Leadership", title_style))
    story.append(Paragraph("Agile Delivery and Management Structure", subtitle_style))
    story.append(
        Paragraph(
            "ABC Technologies operates under a structured two-week agile sprint delivery framework. Each project "
            "lifecycle incorporates continuous integration, automated testing gates, and milestone reviews to ensure "
            "uncompromising software quality and predictable milestone delivery.",
            body_style,
        )
    )
    story.append(
        Paragraph(
            "The company's strategic roadmap and engineering excellence are guided by executive leadership: "
            "Chief Executive Officer Dr. Marcus Vance oversees organizational growth and enterprise partnerships, "
            "while Chief Technology Officer Elena Rostova directs technical architecture and engineering governance.",
            body_style,
        )
    )
    story.append(
        Paragraph(
            "All client onboarding initiatives undergo comprehensive compliance screening, information security "
            "audits, and architecture alignment checkpoints before project execution commences.",
            body_style,
        )
    )
    story.append(PageBreak())

    # ==========================================
    # PAGE 5: Communications & Enquiries (Test 4 & Test 10)
    # ==========================================
    story.append(Paragraph("Client Communications & Contact Information", title_style))
    story.append(Paragraph("Business Enquiries and Corporate Directory", subtitle_style))
    story.append(
        Paragraph(
            "ABC Technologies maintains transparent and accessible channels for client consultation, service "
            "proposals, and technical support engagements.",
            body_style,
        )
    )
    story.append(
        Paragraph(
            "Customers can submit business enquiries through the company's contact page. Prospective clients "
            "are invited to complete the interactive intake form to connect directly with our technical solutions team.",
            body_style,
        )
    )
    story.append(
        Paragraph(
            "Direct corporate contact details are listed as follows:<br/>"
            "- Corporate Email: contact@abctechnologies.com<br/>"
            "- Global Telephone Helpline: +1 (800) 555-0199<br/>"
            "- Headquarters Location: 100 Innovation Boulevard, Suite 400, Tech City, CA 94016, United States",
            body_style,
        )
    )
    story.append(
        Paragraph(
            "The corporate inquiries desk operates Monday through Friday, 8:00 AM to 6:00 PM Pacific Time, with "
            "dedicated support engineers monitoring mission-critical hosting systems twenty-four hours a day.",
            body_style,
        )
    )

    doc.build(story)
    return output_path


if __name__ == "__main__":
    generated = generate_pdf()
    print(f"Sample PDF generated successfully at: {generated}")
