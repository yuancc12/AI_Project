import os, sqlite3
os.chdir(r'C:\Users\Soon Yuan Chi\OneDrive\Desktop\比賽')

# ── 1. UUID v7 格式驗證 ──────────────────────────────────────────────────────
from app_helpers import _uuid7
print("=== UUID v7 格式驗證 ===")
ok = 0
for i in range(5):
    u = _uuid7()
    parts = u.split('-')
    valid = (len(parts) == 5 and parts[2][0] == '7' and parts[3][0] in '89ab')
    status = "OK" if valid else "FAIL"
    print(f"  {u}  [{status}]")
    if valid:
        ok += 1
print(f"結果：{ok}/5 通過\n")

# ── 2. DB 欄位對照 README.pdf ──────────────────────────────────────────────────
conn = sqlite3.connect('butler.db')
cur = conn.cursor()

REQUIRED = {
    'sys_county':    ['code','name','sort','is_deleted','upd_time','cre_time','upd_id','cre_id'],
    'sys_district':  ['code','county_code','name','name_with_county','zip','sort','is_deleted','upd_time','cre_time','upd_id','cre_id'],
    'cms_homepage_service_vendor': ['id','name','description'],
    'cms_homepage_service':        ['id','service_vendor_id','type','name','img_url','description'],
    'pms_form':         ['id','service_vendor_id','type','sub_type','name','intro_content','notice_content','terms_content','review_status','reviewed_id','reviewed_time','is_enable','is_deleted','feature','upd_time','cre_time','upd_id','cre_id'],
    'pms_form_group':   ['id','form_id','name','sort','feature','upd_time','cre_time','upd_id','cre_id'],
    'pms_form_topic':   ['id','form_id','form_group_id','type','title','remark','is_required','sort','is_number_only','minimum_medias_upload','maximum_medias_upload','specified_medias_upload','start_date_offset_days','end_date_offset_days','feature','upd_time','cre_time','upd_id','cre_id'],
    'pms_topic_media':  ['id','form_id','topic_id','img_url','sort','upd_time','cre_time','upd_id','cre_id'],
    'pms_topic_option': ['id','form_id','topic_id','option_name','unit_price','unit','is_quantity','min_quantity','max_quantity','is_quoted_separately','remark','sort','feature','upd_time','cre_time','upd_id','cre_id'],
    'pms_form_feedback':['feedback_no','service_id','platform_code','form_id','feedback_content','form_type','is_read','status','contact_name','contact_name_hash','contact_mobile','contact_mobile_hash','contact_landline','contact_landline_hash','contact_email','contact_email_hash','preferred_contact_time','contact_address_county','contact_address_district','contact_address_detail','contact_address_detail_hash','description','inbr_account_id','cre_time','upd_id','upd_time'],
    'mms_order_record': ['record_id','order_no','service_vendor_id','service_id','platform_code','inbr_account_id','member_name','member_name_hash','member_phone','member_phone_hash','member_email','member_email_hash','order_type','order_status','order_time','deposit_time','confirm_time','service_time','complete_time','cancel_time','deposit_amount','original_amount','discount_amount','shipping_fee_amount','final_amount','refund_amount','order_points','used_points','refund_points','earn_points','point_status','point_grant_time','vendor_data','order_items','remark','cancel_reason','refund_reason','source_file','import_batch','quote_approved_by','quote_approved_time','quote_no','comment_status','is_deleted','cre_id','cre_time','upd_id','upd_time'],
}

print("=== DB Schema vs README.pdf ===")
all_pass = True
for table, required_cols in REQUIRED.items():
    cur.execute('PRAGMA table_info([' + table + '])')
    actual_cols = {r[1] for r in cur.fetchall()}
    missing = [c for c in required_cols if c not in actual_cols]
    if missing:
        print(f"  [FAIL] {table}: 缺少 {missing}")
        all_pass = False
    else:
        print(f"  [OK]   {table}: 所有官方欄位齊全")

conn.close()
print("\n" + ("全部通過！Schema 完全符合 README.pdf" if all_pass else "有欄位缺失，請修正"))
