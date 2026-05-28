import datetime
from decimal import Decimal
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from django.db.models import Subquery
from saleor.brand.models import Brand
from saleor.invoice.models import InvoiceBrand
from saleor.order import FulfillmentStatus
import base64
from saleor.order.models import OrderLine
from saleor.order.utils import get_voucher_discount_for_orderline
from dateutil import parser as date_parser
from saleor.utilities.number_utilities import NumberUtilities
from saleor.utilities.string_utilities import StringUtilities
from saleor.utilities.time_utilities import TimeUtilities
from django.db.models import Max

def get_business_info_details_for_all_brands(brand_id=None):

    if brand_id:
        brands = Brand.objects.filter(id=brand_id).select_related('address')

    else:
        today = TimeUtilities.get_current_date(False)
        current_month = today.month
        brands = Brand.objects.filter(id__in=Subquery(OrderLine.objects.filter(created_at__month=current_month).values('brand_id'))).select_related('address')

    details = dict()

    for brand in brands:
        
        address = [brand.address.street_address_1 + ' ' + brand.address.street_address_2, brand.address.city, brand.address.country_area, brand.address.postal_code]
        
        address_str = list(', '.join(value for value in address if value.strip()))
        
        if len(address_str)>50:
            for i in range(50,len(address_str)):
                if address_str[i] in (' ','-',','):
                    address_str[i]='\n'
                    break

        address_str = ''.join(value for value in address_str)


        details.update({brand:[
                ("Business Name:", brand.company_name, "Helvetica", 8),
                ("Brand Name:", brand.brand_name, "Helvetica", 8),
                ("Address:", address_str, "Helvetica", 8),
                ("Contact Name:", brand.brand_contact_name, "Helvetica", 8),  # Fill this field if available
                ("PAN:", brand.metadata.get('PAN',''), "Helvetica", 8),
                ("GSTIN:", brand.metadata.get('GSTIN',''), "Helvetica", 8),
                ("State:", brand.metadata.get('State',''), "Helvetica", 8)
            ]})

    return details

def get_financial_year():

    today = TimeUtilities.get_current_date(False)
    current_year = today.year

    if today.month < 4:
        financial_year = StringUtilities.convert_number_to_string(current_year - 1)[-2:] + "-" + StringUtilities.convert_number_to_string(current_year)[-2:]

    else:
        financial_year = StringUtilities.convert_number_to_string(current_year)[-2:] + "-" + StringUtilities.convert_number_to_string(current_year + 1)[-2:]

    return financial_year

def get_final_price_paid(orderline_instance):

    line_price_undiscounted = orderline_instance.unit_price_net_amount * orderline_instance.quantity
    line_price_undiscounted+=orderline_instance.shipping_cost_amount
    
    if not orderline_instance.metadata.get('discount_amount'):
        line_discount_amount = get_voucher_discount_for_orderline(orderline_instance).amount

    else:
        line_discount_amount = Decimal(orderline_instance.metadata.get('discount_amount'))

    return line_price_undiscounted - line_discount_amount

def get_revenue(orderline_instance):

    revenue = orderline_instance.metadata.get('revenue')
    return revenue

def get_revenue_with_shopify_markup(orderline_instance):

    revenue = orderline_instance.metadata.get('revenue_with_shopify_markup')
    return revenue

def get_tax_details_for_brand(brand_id,start_date=None,end_date=None):
    
    if start_date and end_date:
        lines = OrderLine.objects.filter(brand_id=brand_id,created_at__gte=start_date,created_at__lte=end_date)

    else:
        today = TimeUtilities.get_current_date(False)
        current_month = today.month
        lines = OrderLine.objects.filter(brand_id=brand_id,created_at__month=current_month)

    revenue_sum = 0 
    
    for line in lines:
        revenue_sum+=get_revenue_with_shopify_markup(line)

    return revenue_sum

def create_invoice_for_brands(brand_id=None,start_date=None,end_date=None,email=''):

    financial_year = get_financial_year()
    business_infos = get_business_info_details_for_all_brands(brand_id) 
    max_serial_no = InvoiceBrand.objects.filter(financial_year=financial_year).aggregate(max_serial_no=Max('serial_no'))['max_serial_no'] or 0
    
    current_month_name = datetime.datetime.now().strftime("%B")

    for brand,business_info in business_infos.items():
        
        revenue = get_tax_details_for_brand(brand.id,start_date,end_date)
        
        taxable_amount = revenue*100/118
        state = brand.metadata.get('State','').lower()

        if state=='delhi':

            IGST = 0 
            SGST = taxable_amount*0.09
            CGST = taxable_amount*0.09

        else:

            IGST = taxable_amount*0.18
            SGST = 0
            CGST = 0

        total_invoice_value = taxable_amount+IGST+SGST+CGST

        tax_values = {
            'taxable_amount':"{0:.2f}".format(taxable_amount),
            'IGST': "{0:.2f}".format(IGST),
            'SGST': "{0:.2f}".format(SGST),
            'CGST': "{0:.2f}".format(CGST),
            'total_invoice_value': "{0:.2f}".format(total_invoice_value)
                      }
        
        max_serial_no+=1
        
        invoice_no = f"ZEPL/{financial_year}/{'{:05d}'.format(max_serial_no)}"
        
        invoice_info = [
                ("Invoice No.:", invoice_no, "Helvetica", 8),
                ("Invoice Date", TimeUtilities.get_current_date(), "Helvetica", 8)
                ]
        
        from io import BytesIO
        l = BytesIO()
        filename= f"{invoice_no}_{brand.brand_name}_{brand.id}.pdf"
        a = create_pdf_with_details(business_info,l,tax_values,invoice_info)
        l.seek(0)

        encoded_file = base64.b64encode(l.getvalue()).decode()
        encoded_file_dict = {'content':encoded_file,"type":'application/pdf','filename':filename}

        mail_type = "brand_ledger_csv"
        subject = f"Tax Invoice : {brand.brand_name}"

        time_frame = f"{start_date} - {end_date}" if start_date and end_date else current_month_name

        msg = f"Hello {brand.brand_name},\nPlease find the Tax invoice for {time_frame} with Invoice no: {invoice_no}."

        attachments = [encoded_file_dict]
        recipient_email=email or 'nitanshub@zaamo.co'

        from saleor.external_services.mail.mail_impl import MailImpl
        mail = MailImpl()
        mail.send_mail_with_attachment(mail_type, msg, subject, attachments, recipient_email, '')

        InvoiceBrand.objects.create(financial_year=financial_year,serial_no=max_serial_no,invoice_no=invoice_no,brand_id=brand.id)
        

def create_pdf_with_details(business_info,filename,tax_values,invoice_info):

    c = canvas.Canvas(filename, pagesize=letter)

    # Define left boundary offset and width of the rectangle
    left_offset = 40
    rectangle_width = 530
    top_offset = 80
   
    # Draw a big rectangle boundary
    c.rect(left_offset, top_offset+100, rectangle_width, 720, stroke=1, fill=0)
    
    # Add heading "Tax Invoice" with black background
    c.setFillColorRGB(0, 0, 0)  # Black color for background
    c.rect(left_offset, 750, rectangle_width, 50, fill=1)  # Black background rectangle
    c.setFillColorRGB(255, 255, 255)  # White color for text
    c.setFont("Helvetica-Bold", 18)
    c.drawString(left_offset + 220, 770, "Tax Invoice")


    # Add Zaamo E-Commerce Private Limited inside the rectangle
    c.setFont("Helvetica-Bold", 14)
    c.setFillColorRGB(0, 0, 0)  # Black color for text
    c.drawString(left_offset + 15, 730, "Zaamo E-Commerce Private Limited")
    zaamo_text_width = c.stringWidth("Zaamo E-Commerce Private Limited")

     # Add image to the right of "Zaamo E-Commerce Private Limited"
    image_path = "zaamo2.png"  # Update with the actual path to your image file
    image_width = 120
    image_height = 90
    img_reader = ImageReader(image_path)
    c.drawImage(img_reader, left_offset + zaamo_text_width + 150, top_offset+550, width=image_width, height=image_height)


    # Add other details inside the rectangle
    details = [
        ("D-81, Basement, Saket, New Delhi-110017", "Helvetica", 8),
        ("GSTIN: 07AABCZ7708E1Z9", "Helvetica", 8),
        ("CIN: U72900DL2021PTC383248", "Helvetica", 8),
        ("MSME: UDYAM-DL-08-0016774", "Helvetica", 8),
        ("PAN: AABCZ7708E", "Helvetica", 8),
        ("Email: Accounts@zaamo.co", "Helvetica", 8),
        ("Tel: +91-9650086309", "Helvetica", 8)
    ]


    # Set initial y-coordinate
    y = 715
    c.setFillColorRGB(0, 0, 0)  # Black color for text
    

    # Add details to the PDF inside the rectangle
    for detail in details:
        text, font, size = detail
        c.setFont(font, size)
        text_width = c.stringWidth(text)
        c.drawString(left_offset + 15, y, text)
        y -= 15  # Move to the next line

    y_curr = y
    # Create a smaller rectangle inside the bigger rectangle
    inner_rect_left = left_offset
    inner_rect_top = top_offset + 515
    inner_rect_width = 530
    inner_rect_height = 18
    c.setFillColorRGB(0, 0, 0)  # Black color for background
    c.rect(inner_rect_left, inner_rect_top, inner_rect_width, inner_rect_height, stroke=1, fill=1)  # Black background rectangle
   
    c.setFillColorRGB(255, 255, 255)  # White color for text
    c.setFont("Helvetica-Bold", 8)
    text_width = c.stringWidth("Bill")
    c.drawString(inner_rect_left + 15, inner_rect_top+6 , "Bill To")

    business_info = business_info

    y=y_curr-30
    c.setFillColorRGB(0, 0, 0)
    label_font = "Helvetica-Bold"
    value_font = "Helvetica"

    y_n = y 

    for detail in invoice_info:
        text1, text2,font, size = detail
        c.setFont(font, size)
        text_width = c.stringWidth(text1)

        c.setFont(label_font, size)
        c.drawString(left_offset + 350, y_n, text1)
        c.setFont(value_font, size)
        c.drawString(left_offset + 415, y_n, text2)
        y_n -= 15  # Move to the next line

    for detail in business_info:
        text1, text2,font, size = detail
        c.setFont(font, size)
        text_width = c.stringWidth(text1)

        if "\n" in text2:
            lines = text2.split("\n")
            # Draw each line separately
            c.setFont(label_font, size)
            c.drawString(left_offset + 15, y, text1)
            #y -= 15  # Move to the next line
            c.setFont(value_font, size)
            for line in lines:
                c.drawString(left_offset + 80, y, line)
                y -= 15  # Move to the next line
        else:
            c.setFont(label_font, size)
            c.drawString(left_offset + 15, y, text1)
            c.setFont(value_font, size)
            c.drawString(left_offset + 80, y, text2)
            y -= 15  # Move to the next line

    y_curr = y

    # Create a smaller rectangle inside the bigger rectangle
    inner_rect_left = left_offset
    inner_rect_top = y_curr-20
    inner_rect_width = 530
    inner_rect_height = 18
    c.setFillColorRGB(0, 0, 0)  # Black color for background
    c.rect(inner_rect_left, inner_rect_top, inner_rect_width, inner_rect_height, stroke=1, fill=1)  # Black background rectangle
   
    c.setFillColorRGB(255, 255, 255)  # White color for text
    c.setFont("Helvetica-Bold", 8)
    text_width = c.stringWidth("Bill")
    c.drawString(inner_rect_left + 15, inner_rect_top+6 , "Sr. No.")
    c.drawString(inner_rect_left + 50, inner_rect_top+6 , "DESCRIPTION OF SERVICE")
    c.drawString(inner_rect_left + 180, inner_rect_top+6 , "HSN/SAC")
    c.drawString(inner_rect_left + 240, inner_rect_top+6 , "Taxable Amount")
    c.drawString(inner_rect_left + 330, inner_rect_top+6 , "IGST")
    c.drawString(inner_rect_left + 380, inner_rect_top+6 , "CGST")
    c.drawString(inner_rect_left + 435, inner_rect_top+6 , "SGST")
    c.drawString(inner_rect_left + 480, inner_rect_top+6 , "TOTAL")


     # Create a smaller rectangle inside the bigger rectangle
    inner_rect_left = left_offset
    inner_rect_top = y_curr-36
    inner_rect_width = 530
    inner_rect_height = 18
    c.setFillColorRGB(255, 255, 255)
    c.rect(inner_rect_left, inner_rect_top, inner_rect_width, inner_rect_height, stroke=1, fill=1)  # Black background rectangle
   
    c.setFillColorRGB(0, 0, 0)  
    c.setFont("Helvetica-Bold", 8)
    text_width = c.stringWidth("Bill")
    c.drawString(inner_rect_left + 15, inner_rect_top+6 , "1")
    c.drawString(inner_rect_left + 50, inner_rect_top+6 , "Zaamo Platform Service Charges")
    c.drawString(inner_rect_left + 180, inner_rect_top+6 , "998313")
    c.drawString(inner_rect_left + 240, inner_rect_top+6 , tax_values['taxable_amount'])
    c.drawString(inner_rect_left + 330, inner_rect_top+6 , tax_values['IGST'])
    c.drawString(inner_rect_left + 380, inner_rect_top+6 , tax_values['CGST'])
    c.drawString(inner_rect_left + 440, inner_rect_top+6 , tax_values['SGST'])
    c.drawString(inner_rect_left + 480, inner_rect_top+6 , tax_values['total_invoice_value'])


    # Create a smaller rectangle inside the bigger rectangle
    inner_rect_left = left_offset
    inner_rect_top = y_curr-52
    inner_rect_width = 530
    inner_rect_height = 18
    c.setFillColorRGB(0, 0, 0)  # Black color for background
    c.rect(inner_rect_left, inner_rect_top, inner_rect_width, inner_rect_height, stroke=1, fill=1)  # Black background rectangle
   
    c.setFillColorRGB(255, 255, 255)  # White color for text
    c.setFont("Helvetica-Bold", 8)
    c.drawString(inner_rect_left + 10, inner_rect_top+6 , "Total")
    c.drawString(inner_rect_left + 50, inner_rect_top+6 , "")
    c.drawString(inner_rect_left + 180, inner_rect_top+6 , "")
    c.drawString(inner_rect_left + 240, inner_rect_top+6 , tax_values['taxable_amount'])
    c.drawString(inner_rect_left + 330, inner_rect_top+6 , tax_values['IGST'])
    c.drawString(inner_rect_left + 380, inner_rect_top+6 , tax_values['CGST'])
    c.drawString(inner_rect_left + 435, inner_rect_top+6 , tax_values['SGST'])
    c.drawString(inner_rect_left + 480, inner_rect_top+6 , tax_values['total_invoice_value'])


    # Create a smaller rectangle inside the bigger rectangle
    inner_rect_left = left_offset+370
    inner_rect_top = y_curr-70
    inner_rect_width = 160
    inner_rect_height = 18
    c.setFillColorRGB(255, 255, 255) 
    c.rect(inner_rect_left, inner_rect_top, inner_rect_width, inner_rect_height, stroke=1, fill=1)  # Black background rectangle
   
    c.setFillColorRGB(0, 0, 0)  
    c.setFont("Helvetica-Bold", 8)
    c.drawString(inner_rect_left + 10, inner_rect_top+6 , "Taxable Value")
    c.drawString(inner_rect_left + 120, inner_rect_top+6 , tax_values['taxable_amount'])


        # Create a smaller rectangle inside the bigger rectangle
    # inner_rect_left = left_offset+380
    inner_rect_top = y_curr-88
    # inner_rect_width = 110
    # inner_rect_height = 18
    c.setFillColorRGB(255, 255, 255) 
    c.rect(inner_rect_left, inner_rect_top, inner_rect_width, inner_rect_height, stroke=1, fill=1)  # Black background rectangle
   
    c.setFillColorRGB(0, 0, 0)  
    c.setFont("Helvetica-Bold", 8)
    c.drawString(inner_rect_left + 10, inner_rect_top+6 , "IGST @ 18%")
    c.drawString(inner_rect_left + 120, inner_rect_top+6 , tax_values['IGST'])


        # Create a smaller rectangle inside the bigger rectangle
    # inner_rect_left = left_offset+380
    inner_rect_top = y_curr-106
    # inner_rect_width = 110
    # inner_rect_height = 18
    c.setFillColorRGB(255, 255, 255) 
    c.rect(inner_rect_left, inner_rect_top, inner_rect_width, inner_rect_height, stroke=1, fill=1)  # Black background rectangle
   
    c.setFillColorRGB(0, 0, 0)  
    c.setFont("Helvetica-Bold", 8)
    c.drawString(inner_rect_left + 10, inner_rect_top+6 , "CGST @ 9%")
    c.drawString(inner_rect_left + 120, inner_rect_top+6 , tax_values['CGST'])



    # inner_rect_left = left_offset+380
    inner_rect_top = y_curr-124
    # inner_rect_width = 110
    # inner_rect_height = 18
    c.setFillColorRGB(255, 255, 255) 
    c.rect(inner_rect_left, inner_rect_top, inner_rect_width, inner_rect_height, stroke=1, fill=1)  # Black background rectangle
   
    c.setFillColorRGB(0, 0, 0)  
    c.setFont("Helvetica-Bold", 8)
    c.drawString(inner_rect_left + 10, inner_rect_top+6 , "SGST @ 9%")
    c.drawString(inner_rect_left + 120, inner_rect_top+6 , tax_values['SGST'])

    # inner_rect_left = left_offset+380
    inner_rect_top = y_curr-140
    # inner_rect_width = 110
    # inner_rect_height = 18
    c.setFillColorRGB(255, 255, 255) 
    c.rect(inner_rect_left, inner_rect_top, inner_rect_width, inner_rect_height, stroke=1, fill=1)  # Black background rectangle
   
    c.setFillColorRGB(0, 0, 0)  
    c.setFont("Helvetica-Bold", 7)
    c.drawString(inner_rect_left + 10, inner_rect_top+6 , "TOTAL INVOICE VALUE")
    c.drawString(inner_rect_left + 120, inner_rect_top+6 , tax_values['total_invoice_value'])


    # Add other details inside the rectangle
    details = [
        ("Amount of Tax subject to Reverse Charges: No", "Helvetica-Bold", 8),
    ]

    # Set initial y-coordinate
    y = y_curr-62
    c.setFillColorRGB(0, 0, 0)  # Black color for text
    

    # Add details to the PDF inside the rectangle
    for detail in details:
        text, font, size = detail
        c.setFont(font, size)
        c.drawString(left_offset +10, y, text)
        y -= 10  # Move to the next line
   
    y_curr=y

     # Add other details inside the rectangle
    details = [
        ("For Zaamo E-Commerce Private Limtied", "Helvetica-Bold", 8),
    ]

    # Set initial y-coordinate
    y = y_curr-140
    c.setFillColorRGB(0, 0, 0)  # Black color for text
    

    # Add details to the PDF inside the rectangle
    for detail in details:
        text, font, size = detail
        c.setFont(font, size)
        c.drawString(left_offset +370, y, text)
        y -= 10  # Move to the next line

    
    details = [
        ("Authorised Signatory", "Helvetica-Bold", 8),
    ]

    # Set initial y-coordinate
    y = y_curr-190
    c.setFillColorRGB(0, 0, 0)  # Black color for text
    

    # Add details to the PDF inside the rectangle
    for detail in details:
        text, font, size = detail
        c.setFont(font, size)
        c.drawString(left_offset +430, y, text)
        y -= 10  # Move to the next line


        # Add other details inside the rectangle
    details = [
        ("Terms & Instructions:", "Helvetica-Bold", 8),
        ("1- TDS to be deducted @ 2% under section 194C of the Income Tax Act 1961", "Helvetica", 8),
        ("""2- If any correction requires from our site in the invoice, kindly let us know within 7 days from""", "Helvetica", 8),
        ("""    the day when you received from our team.""", "Helvetica", 8),
        ("""3- All Dispute will be Subject to "Delhi" Jurisdiction""", "Helvetica", 8)
    ]

    # Set initial y-coordinate
    y = y_curr-15
    c.setFillColorRGB(0, 0, 0)  # Black color for text
    

    # Add details to the PDF inside the rectangle
    for detail in details:
        text, font, size = detail
        c.setFont(font, size)
        text_width = c.stringWidth(text)
        c.drawString(left_offset + 15, y, text)
        y -= 15  # Move to the next line
   
    y_curr=y

    business_info = [
        ("BANK DETAILS:", "", "Helvetica", 8),
        ("BENEFICIARY NAME:", "ZAAMO E-COMMERCE PVT LTD", "Helvetica", 8),
        ("BANK NAME: ", "HDFC BANK", "Helvetica", 8),
        ("BRANCH NAME:", "GEETANJALI", "Helvetica", 8),  # Fill this field if available
        ("BANK A/c NO.", "50200060265925", "Helvetica", 8),
        ("IFSC CODE:", "HDFC0000614", "Helvetica", 8),
        ("UPI:", "9773654171@axl", "Helvetica", 8)
    ]

    y=y_curr-25
    
    c.setFillColorRGB(0, 0, 0)
    label_font = "Helvetica-Bold"
    value_font = "Helvetica"

    for detail in business_info:
        text1, text2,font, size = detail
        c.setFont(font, size)
        text_width = c.stringWidth(text1)

        if "\n" in text2:
            lines = text2.split("\n")
            # Draw each line separately
            c.setFont(label_font, size)
            c.drawString(left_offset + 15, y, text1)
            #y -= 15  # Move to the next line
            c.setFont(value_font, size)
            for line in lines:
                c.drawString(left_offset + 100, y, line)
                y -= 12  # Move to the next line
        else:
            c.setFont(label_font, size)
            c.drawString(left_offset + 15, y, text1)
            c.setFont(value_font, size)
            c.drawString(left_offset + 100, y, text2)
            y -= 12  # Move to the next line

    
    y_curr = y
    
    details = [
        ("Thank you for your business!", "Helvetica-Bold", 8),
    ]

    # Set initial y-coordinate
    y = y_curr
    c.setFillColorRGB(0, 0, 0)  # Black color for text
    

    # Add details to the PDF inside the rectangle
    for detail in details:
        text, font, size = detail
        c.setFont(font, size)
        c.drawString(left_offset +200, y, text)
        y -= 10  # Move to the next line


    # Save the PDF

    c.save()
    return c
   

    

# Call the function to create the PDF


# Call the function to create the PDF
# create_pdf_with_details("example.pdf")




def run():
    from io import BytesIO
    l = BytesIO()

    tax_values = {
    'taxable_amount':"{0:.2f}".format(2),
    'IGST': "{0:.2f}".format(2),
    'SGST': "{0:.2f}".format(2),
    'CGST': "{0:.2f}".format(2),
    'total_invoice_value': "{0:.2f}".format(2)
                }
    a = create_pdf_with_details([],'s.pdf',tax_values,[])
    l.seek(0)

    import base64

    d = base64.b64encode(l.getvalue()).decode()

    di = {'content':d,"type":'application/pdf','filename':'test.pdf'}
    mail_type = "brand_ledger_csv"
    subject = "pdf test"
    msg = "pdf test"
    attachments = [di]
    recipient_email='nitanshub@zaamo.co'
    from saleor.external_services.mail.mail_impl import MailImpl
    mail = MailImpl()
    mail.send_mail_with_attachment(mail_type, msg, subject, attachments, recipient_email, '')
