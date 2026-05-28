from .view_impl import export_brand_inventory_csv, export_csv_for_master_dashboard,export_csv_for_brand_upi_payment,export_csv_for_brand_bank_payment,export_csv_for_influencer_upi_payment,export_csv_for_influencer_bank_payment, export_csv_for_store_gmv,export_csv_for_brand_price_record,export_csv_to_mail, export_reel_up_brand_details, export_shopify_product_details, order_related_calculations, send_csv_to_brand_owners_request, send_invoice_email_for_brand, update_split_price_published_products
from .view_impl import export_csv_for_sourcing_request, export_csv_for_brand_dashboard, export_csv_for_brand_ledger, export_csv_for_gmv, export_csv_for_brand_sourcing_request, export_csv_for_influencer_ledger,export_ad_data_in_FB_format_by_brand, explore_product_status, update_search_image
from .view_impl import export_csv_for_botd_stores,export_tax_reports, export_zaamo_shopify_order,export_csv_for_user_contacts, export_csv_for_coupons, export_csv_for_all_brand_details, export_csv_for_explore_products, upload_csv_for_explore_products,export_csv_for_orderline_cashgram, export_csv_for_published_products, export_shopify_csv, export_csv_for_brand_list
from django.urls import path

urlpatterns = [
    path('export_csv_for_master_dashboard', export_csv_for_master_dashboard, name="export_csv_for_master_dashboard"),
    path('export_csv_for_brand_upi_payment',export_csv_for_brand_upi_payment,name = "export_csv_for_brand_upi_payment"),
    path('export_csv_for_brand_neft_payment',export_csv_for_brand_bank_payment,name = "export_csv_for_brand_bank_payment"),
    path('export_csv_for_influencer_upi_payment',export_csv_for_influencer_upi_payment,name = "export_csv_for_influencer_upi_payment"),
    path('export_csv_for_influencer_neft_payment',export_csv_for_influencer_bank_payment,name = "export_csv_for_influencer_bank_payment"),
    path('export_csv_for_store_gmv', export_csv_for_store_gmv, name = "export_csv_for_store_gmv"),
    path('export_csv_for_brand_price_record', export_csv_for_brand_price_record, name="export_csv_for_brand_price_record"),
    path('export_csv_for_sourcing_request', export_csv_for_sourcing_request, name="export_csv_for_sourcing_request"),
    path('export_csv_for_brand_sourcing_request', export_csv_for_brand_sourcing_request, name="export_csv_for_brand_sourcing_request"),
    path('export_csv_for_brand_dashboard', export_csv_for_brand_dashboard, name='export_csv_for_brand_dashboard'),
    path('export_csv_for_brand_ledger', export_csv_for_brand_ledger, name='export_csv_for_brand_ledger'),
    path('export_csv_for_brand_list', export_csv_for_brand_list, name='export_csv_for_brand_list'),
    path('export_csv_for_gmv', export_csv_for_gmv, name='export_csv_for_gmv'),
    path('export_csv_for_influencer_ledger', export_csv_for_influencer_ledger, name='export_csv_for_influencer_ledger'),
    path('export_csv_and_email',export_csv_to_mail,name='send_csv_to_mail'),
    path('export_csv_for_user_contacts', export_csv_for_user_contacts, name='export_csv_for_user_contacts'),
    path('export_csv_for_botd_stores', export_csv_for_botd_stores, name='export_csv_for_botd_stores'),
    path('export_csv_for_coupons', export_csv_for_coupons, name='export_csv_for_coupons'),
    path('export_csv_for_all_brand_details', export_csv_for_all_brand_details, name='export_csv_for_all_brand_details'),
    path('export_csv_for_brand_owners', send_csv_to_brand_owners_request, name='export_csv_for_brand_owners'),
    path('export_csv_for_explore_products', export_csv_for_explore_products, name='export_csv_for_explore_products'),
    path('upload_csv_for_explore_products', upload_csv_for_explore_products, name='upload_csv_for_explore_products'),
    path('export_csv_for_orderline_cashgram',export_csv_for_orderline_cashgram,name='export_csv_for_orderline_cashgram'),
    path('export_csv_for_published_products', export_csv_for_published_products, name='export_csv_for_published_products'),
    path('update_split_price_published_products', update_split_price_published_products, name='update_split_price_published_products'),
    path('export_ad_data_in_FB_format_by_brand', export_ad_data_in_FB_format_by_brand, name='export_ad_data_in_FB_format_by_brand'),
    path('export_brand_inventory_csv', export_brand_inventory_csv, name='export_brand_inventory_csv'),
    path('export_shopify_csv', export_shopify_csv, name='export_shopify_csv'),
    path('export_shopify_product_details', export_shopify_product_details, name='export_shopify_product_details'),
    path('explore_product_status', explore_product_status, name='explore_product_status'),
    path('update_search_image', update_search_image, name='update_search_image'),
    path('export_zaamo_shopify_order', export_zaamo_shopify_order, name='export_zaamo_shopify_order'),
    path('export_tax_reports', export_tax_reports, name="export_tax_reports"),
    path('export_reel_up_brand_details', export_reel_up_brand_details, name='export_reel_up_brand_details'),
    path('send_invoice_email_for_brand', send_invoice_email_for_brand, name='send_invoice_email_for_brand'),
    path('order_related_calculations', order_related_calculations, name='order_related_calculations'),
    
]
