# -*- coding: utf-8 -*-
"""
seed.py — 建立健身採買助手的 SQLite 資料庫並塞入擬真假資料。
執行：  python seed.py
產出：  butler.db
"""
import sqlite3
import os

DB = os.path.join(os.path.dirname(__file__), "butler.db")

SCHEMA = """
DROP TABLE IF EXISTS pms_form_feedback;
DROP TABLE IF EXISTS mms_order_record;
DROP TABLE IF EXISTS pms_topic_option;
DROP TABLE IF EXISTS pms_form_topic;
DROP TABLE IF EXISTS pms_form_group;
DROP TABLE IF EXISTS pms_form;
DROP TABLE IF EXISTS cms_homepage_service;
DROP TABLE IF EXISTS cms_homepage_service_vendor;
DROP TABLE IF EXISTS sys_district;
DROP TABLE IF EXISTS sys_county;
DROP TABLE IF EXISTS fitness_product;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS inquiry;
DROP TABLE IF EXISTS course_enrollment;
DROP TABLE IF EXISTS gym_course;
DROP TABLE IF EXISTS partner_vendor;

CREATE TABLE fitness_product (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    vendor     TEXT NOT NULL,   -- 萬家福 / 7-11 / 康是美 / 統一生機
    category   TEXT NOT NULL,   -- 蛋白質 / 主食 / 蔬果 / 乳製品 / 保健品 / 即食
    protein_g  REAL NOT NULL DEFAULT 0,
    calories   INTEGER NOT NULL DEFAULT 0,
    price      INTEGER NOT NULL,
    stock      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    password      TEXT NOT NULL,
    gender        TEXT NOT NULL DEFAULT '',
    birthday      TEXT NOT NULL DEFAULT '',
    height_cm     REAL NOT NULL DEFAULT 0,
    weight_kg     REAL NOT NULL DEFAULT 0,
    email         TEXT NOT NULL DEFAULT '',
    dietary_pref  TEXT NOT NULL DEFAULT '',
    county_code   TEXT NOT NULL DEFAULT '',
    district_code TEXT NOT NULL DEFAULT '',
    address       TEXT NOT NULL DEFAULT '',
    contact_phone TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL
);

CREATE TABLE sys_county (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE sys_district (
    code        TEXT NOT NULL,
    county_code TEXT NOT NULL,
    name        TEXT NOT NULL,
    zip         TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (code, county_code)
);

CREATE TABLE cms_homepage_service_vendor (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    category    TEXT NOT NULL DEFAULT '',
    rating      REAL NOT NULL DEFAULT 5.0,
    phone       TEXT NOT NULL DEFAULT '',
    address     TEXT NOT NULL DEFAULT '',
    county_code TEXT NOT NULL DEFAULT '',
    is_enable   INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE cms_homepage_service (
    id        INTEGER PRIMARY KEY,
    vendor_id INTEGER NOT NULL,
    name      TEXT NOT NULL,
    type      TEXT NOT NULL DEFAULT '11',
    intro     TEXT NOT NULL DEFAULT '',
    is_enable INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE pms_form (
    id            INTEGER PRIMARY KEY,
    service_id    INTEGER NOT NULL,
    name          TEXT NOT NULL,
    intro_content TEXT NOT NULL DEFAULT '',
    is_enable     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE pms_form_group (
    id      INTEGER PRIMARY KEY,
    form_id INTEGER NOT NULL,
    name    TEXT NOT NULL,
    sort    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE pms_form_topic (
    id          INTEGER PRIMARY KEY,
    form_id     INTEGER NOT NULL,
    group_id    INTEGER NOT NULL,
    type        INTEGER NOT NULL DEFAULT 1,
    title       TEXT NOT NULL,
    remark      TEXT NOT NULL DEFAULT '',
    is_required INTEGER NOT NULL DEFAULT 0,
    sort        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE pms_topic_option (
    id          INTEGER PRIMARY KEY,
    topic_id    INTEGER NOT NULL,
    option_name TEXT NOT NULL,
    unit_price  INTEGER NOT NULL DEFAULT 0,
    unit        TEXT NOT NULL DEFAULT '',
    sort        INTEGER NOT NULL DEFAULT 0
);

-- 健身採買諮詢單（submit_inquiry 寫入；dispatch_delivery 更新狀態）
CREATE TABLE pms_form_feedback (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    feedback_no   TEXT UNIQUE NOT NULL,
    form_id       INTEGER NOT NULL DEFAULT 1,
    service_id    INTEGER NOT NULL DEFAULT 1,
    goal          TEXT NOT NULL DEFAULT '',
    budget        INTEGER NOT NULL DEFAULT 0,
    keyword       TEXT NOT NULL DEFAULT '',
    county_code   TEXT NOT NULL DEFAULT '',
    district_code TEXT NOT NULL DEFAULT '',
    contact_name  TEXT NOT NULL DEFAULT '',
    contact_phone TEXT NOT NULL DEFAULT '',
    note          TEXT NOT NULL DEFAULT '',
    address       TEXT NOT NULL DEFAULT '',
    user_id       INTEGER NOT NULL DEFAULT 0,
    products_json    TEXT NOT NULL DEFAULT '',
    user_reply       TEXT NOT NULL DEFAULT '',
    status           TEXT NOT NULL DEFAULT '待處理',
    vendor_reply     TEXT NOT NULL DEFAULT '',
    accepted_at      TEXT NOT NULL DEFAULT '',
    images_json      TEXT NOT NULL DEFAULT '[]',
    feedback_content TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL
);

-- 合作廠商（餐廳、搬家、清潔、健身房等）
CREATE TABLE partner_vendor (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    category    TEXT NOT NULL,   -- 健身房 / 餐廳 / 搬家 / 清潔
    phone       TEXT NOT NULL DEFAULT '',
    address     TEXT NOT NULL DEFAULT '',
    county_code TEXT NOT NULL DEFAULT '',
    rating      REAL NOT NULL DEFAULT 5.0,
    description TEXT NOT NULL DEFAULT '',
    is_enable   INTEGER NOT NULL DEFAULT 1
);

-- 健身房每月課程
CREATE TABLE gym_course (
    id           INTEGER PRIMARY KEY,
    gym_id       INTEGER NOT NULL,
    course_name  TEXT NOT NULL,
    coach        TEXT NOT NULL DEFAULT '',
    course_type  TEXT NOT NULL DEFAULT '',  -- 有氧 / 重訓 / 瑜珈 / 格鬥 / 舞蹈
    weekday      TEXT NOT NULL DEFAULT '',  -- 週一,週三,週五 (逗號分隔)
    time_start   TEXT NOT NULL DEFAULT '',  -- HH:MM
    duration_min INTEGER NOT NULL DEFAULT 60,
    max_slots    INTEGER NOT NULL DEFAULT 20,
    enrolled     INTEGER NOT NULL DEFAULT 0,
    price_month  INTEGER NOT NULL DEFAULT 0,
    month        TEXT NOT NULL DEFAULT '',  -- YYYYMM
    min_students INTEGER NOT NULL DEFAULT 8,  -- 最低開課人數
    status       TEXT NOT NULL DEFAULT '招生中',  -- 招生中 / 已開課 / 已取消
    is_enable    INTEGER NOT NULL DEFAULT 1
);

-- 課程報名記錄（enroll_gym_course 寫入）
CREATE TABLE course_enrollment (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id     INTEGER NOT NULL,
    feedback_no   TEXT NOT NULL DEFAULT '',  -- 對應諮詢單（可空）
    contact_name  TEXT NOT NULL DEFAULT '',
    contact_phone TEXT NOT NULL DEFAULT '',
    note          TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT '報名中',  -- 報名中 / 確認開課 / 已取消
    notified      INTEGER NOT NULL DEFAULT 0,       -- 1=已通知開課
    enrolled_at   TEXT NOT NULL
);

-- 外送訂單記錄（dispatch_delivery 寫入）
CREATE TABLE mms_order_record (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    order_no          TEXT UNIQUE NOT NULL,
    feedback_no       TEXT NOT NULL,
    order_type        TEXT NOT NULL DEFAULT '01',
    order_status      TEXT NOT NULL DEFAULT '12',
    platform_code     TEXT NOT NULL DEFAULT '01',
    service_vendor_id INTEGER NOT NULL DEFAULT 0,
    service_id        INTEGER NOT NULL DEFAULT 0,
    inbr_account_id   TEXT NOT NULL DEFAULT '',
    vendor_name       TEXT NOT NULL DEFAULT '',
    estimated_minutes INTEGER NOT NULL DEFAULT 60,
    reply_message     TEXT NOT NULL DEFAULT '',
    status            TEXT NOT NULL DEFAULT '01',
    driver_name       TEXT NOT NULL DEFAULT '',
    delivery_company  TEXT NOT NULL DEFAULT '',
    tracking_no       TEXT NOT NULL DEFAULT '',
    deposit_amount    REAL NOT NULL DEFAULT 0,
    final_amount      REAL NOT NULL DEFAULT 0,
    order_items       TEXT NOT NULL DEFAULT '',
    created_at        TEXT NOT NULL
);
"""

# id, name, vendor, category, protein_g, calories, price, stock
PRODUCTS = [
    (1,  "雞胸肉(去骨)",        "萬家福",  "蛋白質", 31.0, 165,  65,  120),
    (2,  "舒肥雞胸肉(原味)",    "7-11",    "即食",   23.0, 110,  49,   80),
    (3,  "醬燒舒肥雞胸肉",      "7-11",    "即食",   20.0, 130,  55,   70),
    (4,  "水煮蛋(2入)",         "7-11",    "蛋白質",  6.0,  70,  15,  150),
    (5,  "鮪魚罐頭(水漬)",      "7-11",    "蛋白質", 26.0, 130,  45,   90),
    (6,  "無糖豆漿(450ml)",     "7-11",    "乳製品",  7.0,  70,  30,  100),
    (7,  "低脂牛奶(400ml)",     "7-11",    "乳製品",  8.0, 100,  35,  100),
    (8,  "蒸地瓜(170g)",        "7-11",    "主食",    2.0, 100,  35,   60),
    (9,  "鮭魚排(180g)",        "萬家福",  "蛋白質", 25.0, 200, 180,   40),
    (10, "牛腱肉(200g)",        "萬家福",  "蛋白質", 28.0, 175, 150,   30),
    (11, "雞蛋(10入)",          "萬家福",  "蛋白質",  6.0,  70,  65,  200),
    (12, "鮮蝦仁(200g)",        "萬家福",  "蛋白質", 24.0, 100, 180,   50),
    (13, "板豆腐(300g)",        "萬家福",  "蛋白質",  8.0,  75,  30,  100),
    (14, "希臘優格(無糖)",      "萬家福",  "乳製品", 10.0, 100,  65,   60),
    (15, "茅屋起司(200g)",      "萬家福",  "乳製品", 11.0, 100, 120,   30),
    (16, "地瓜(600g)",          "萬家福",  "主食",    2.0, 130,  40,  200),
    (17, "花椰菜(400g)",        "萬家福",  "蔬果",    3.0,  30,  35,  100),
    (18, "冷凍毛豆(500g)",      "萬家福",  "蔬果",   11.0, 120,  60,   80),
    (19, "菠菜(300g)",          "萬家福",  "蔬果",    3.0,  25,  30,  120),
    (20, "酪梨",                "萬家福",  "蔬果",    2.0, 160,  60,   60),
    (21, "乳清蛋白粉(巧克力)",  "康是美",  "保健品", 25.0, 120, 1280,  30),
    (22, "乳清蛋白粉(原味)",    "康是美",  "保健品", 25.0, 110, 1180,  25),
    (23, "高蛋白能量棒",        "康是美",  "即食",   20.0, 200,  89,   40),
    (24, "BCAA胺基酸粉",        "康是美",  "保健品",  0.0,  10, 890,   25),
    (25, "胺基酸補充飲(330ml)", "康是美",  "保健品",  5.0,  30,  49,   60),
    (26, "膠原蛋白粉",          "康是美",  "保健品",  9.0,  40, 650,   35),
    (27, "燕麥片(500g)",        "統一生機", "主食",  13.0, 389, 150,   60),
    (28, "全穀雜糧麵包",        "統一生機", "主食",   7.0, 250,  85,   40),
    (29, "綜合堅果(200g)",      "統一生機", "保健品",  8.0, 180, 120,  50),
    (30, "黑豆漿(946ml)",       "統一生機", "乳製品",  9.0,  80,  55,   50),
    (31, "燕麥奶(1000ml)",      "統一生機", "乳製品",  3.0, 120,  85,   40),
]

COUNTIES = [
    ('01', '台北市'), ('02', '新北市'), ('03', '基隆市'), ('04', '桃園市'),
    ('05', '新竹縣'), ('06', '新竹市'), ('07', '苗栗縣'), ('08', '台中市'),
    ('09', '南投縣'), ('10', '彰化縣'), ('11', '雲林縣'), ('12', '嘉義縣'),
    ('13', '嘉義市'), ('14', '台南市'), ('15', '高雄市'), ('16', '屏東縣'),
    ('17', '宜蘭縣'), ('18', '花蓮縣'), ('19', '台東縣'), ('20', '澎湖縣'),
    ('21', '金門縣'), ('22', '連江縣'),
]

DISTRICTS = [
    # 台北市 01
    ('001','01','中正區','100'), ('002','01','大同區','103'), ('003','01','中山區','104'),
    ('004','01','萬華區','108'), ('005','01','信義區','110'), ('006','01','松山區','105'),
    ('007','01','大安區','106'), ('008','01','南港區','115'), ('009','01','北投區','112'),
    ('010','01','內湖區','114'), ('011','01','士林區','111'), ('012','01','文山區','116'),
    # 新北市 02
    ('013','02','板橋區','220'), ('014','02','新莊區','242'), ('015','02','泰山區','243'),
    ('016','02','林口區','244'), ('017','02','淡水區','251'), ('018','02','金山區','208'),
    ('019','02','八里區','249'), ('020','02','萬里區','207'), ('021','02','石門區','253'),
    ('022','02','三芝區','252'), ('023','02','瑞芳區','224'), ('024','02','汐止區','221'),
    ('025','02','平溪區','226'), ('026','02','貢寮區','228'), ('027','02','雙溪區','227'),
    ('028','02','深坑區','222'), ('029','02','石碇區','223'), ('030','02','新店區','231'),
    ('031','02','坪林區','232'), ('032','02','烏來區','233'), ('033','02','中和區','235'),
    ('034','02','永和區','234'), ('035','02','土城區','236'), ('036','02','三峽區','237'),
    ('037','02','樹林區','238'), ('038','02','鶯歌區','239'), ('039','02','三重區','241'),
    ('040','02','蘆洲區','247'), ('041','02','五股區','248'),
    # 基隆市 03
    ('042','03','仁愛區','200'), ('043','03','中正區','202'), ('044','03','信義區','201'),
    ('045','03','中山區','203'), ('046','03','安樂區','204'), ('047','03','暖暖區','205'),
    ('048','03','七堵區','206'),
    # 桃園市 04
    ('049','04','桃園區','330'), ('050','04','中壢區','320'), ('051','04','平鎮區','324'),
    ('052','04','八德區','334'), ('053','04','楊梅區','326'), ('054','04','蘆竹區','338'),
    ('055','04','龜山區','333'), ('056','04','龍潭區','325'), ('057','04','大溪區','335'),
    ('058','04','大園區','337'), ('059','04','觀音區','328'), ('060','04','新屋區','327'),
    ('061','04','復興區','336'),
    # 新竹縣 05
    ('062','05','竹北市','302'), ('063','05','竹東鎮','310'), ('064','05','新埔鎮','305'),
    ('065','05','關西鎮','306'), ('066','05','峨眉鄉','315'), ('067','05','寶山鄉','308'),
    ('068','05','北埔鄉','314'), ('069','05','橫山鄉','312'),
    # 台南市 14（部分區域）
    ('238','14','山上區','743'), ('239','14','新市區','744'), ('240','14','安定區','745'),
    # 高雄市 15
    ('241','15','楠梓區','811'), ('242','15','左營區','813'), ('243','15','鼓山區','804'),
    ('244','15','三民區','807'), ('245','15','鹽埕區','803'), ('246','15','前金區','801'),
    ('247','15','新興區','800'), ('248','15','苓雅區','802'), ('249','15','前鎮區','806'),
    ('250','15','小港區','812'), ('251','15','旗津區','805'), ('252','15','鳳山區','830'),
    ('253','15','大寮區','831'), ('254','15','鳥松區','833'), ('255','15','林園區','832'),
    ('256','15','仁武區','814'), ('257','15','大樹區','840'), ('258','15','大社區','815'),
    ('259','15','岡山區','820'), ('260','15','路竹區','821'), ('261','15','橋頭區','825'),
    ('262','15','梓官區','826'), ('263','15','彌陀區','827'), ('264','15','永安區','828'),
    ('265','15','燕巢區','824'), ('266','15','田寮區','823'), ('267','15','阿蓮區','822'),
    ('268','15','茄萣區','852'), ('269','15','湖內區','829'), ('270','15','旗山區','842'),
    ('271','15','美濃區','843'), ('272','15','內門區','845'), ('273','15','杉林區','846'),
    ('274','15','甲仙區','847'), ('275','15','六龜區','844'), ('276','15','茂林區','851'),
    ('277','15','桃源區','848'), ('278','15','那瑪夏區','849'),
    # 屏東縣 16
    ('279','16','屏東市','900'), ('280','16','潮州鎮','920'), ('281','16','東港鎮','928'),
    ('282','16','恆春鎮','946'), ('283','16','萬丹鄉','913'), ('284','16','長治鄉','908'),
    ('285','16','麟洛鄉','909'), ('286','16','九如鄉','904'), ('287','16','里港鄉','905'),
    ('288','16','鹽埔鄉','907'), ('289','16','高樹鄉','906'), ('290','16','萬巒鄉','923'),
    ('291','16','內埔鄉','912'), ('292','16','竹田鄉','911'), ('293','16','新埤鄉','925'),
    ('294','16','枋寮鄉','940'), ('295','16','新園鄉','932'), ('296','16','崁頂鄉','924'),
    ('297','16','林邊鄉','927'), ('298','16','南州鄉','926'), ('299','16','佳冬鄉','931'),
    ('300','16','琉球鄉','929'), ('301','16','車城鄉','944'), ('302','16','滿州鄉','947'),
    ('303','16','枋山鄉','941'), ('304','16','霧台鄉','902'), ('305','16','瑪家鄉','903'),
    ('306','16','泰武鄉','921'), ('307','16','來義鄉','922'), ('308','16','春日鄉','942'),
    ('309','16','獅子鄉','943'), ('310','16','牡丹鄉','945'), ('311','16','三地門鄉','901'),
    # 宜蘭縣 17
    ('312','17','宜蘭市','260'), ('313','17','羅東鎮','265'), ('314','17','蘇澳鎮','270'),
    ('315','17','頭城鎮','261'), ('316','17','礁溪鄉','262'), ('317','17','壯圍鄉','263'),
    ('318','17','員山鄉','264'), ('319','17','冬山鄉','269'), ('320','17','五結鄉','268'),
    ('321','17','三星鄉','266'), ('322','17','大同鄉','267'), ('323','17','南澳鄉','272'),
    # 花蓮縣 18
    ('324','18','花蓮市','970'), ('325','18','鳳林鎮','975'), ('326','18','玉里鎮','981'),
    ('327','18','新城鄉','971'), ('328','18','吉安鄉','973'), ('329','18','壽豐鄉','974'),
    ('330','18','秀林鄉','972'), ('331','18','光復鄉','976'), ('332','18','豐濱鄉','977'),
    ('333','18','瑞穗鄉','978'), ('334','18','萬榮鄉','979'), ('335','18','富里鄉','983'),
    ('336','18','卓溪鄉','982'),
    # 台東縣 19
    ('337','19','台東市','950'), ('338','19','成功鎮','961'), ('339','19','關山鎮','956'),
    ('340','19','長濱鄉','962'), ('341','19','海端鄉','957'), ('342','19','池上鄉','958'),
    ('343','19','東河鄉','959'), ('344','19','鹿野鄉','955'), ('345','19','延平鄉','953'),
    ('346','19','卑南鄉','954'), ('347','19','金峰鄉','964'), ('348','19','大武鄉','965'),
    ('349','19','達仁鄉','966'), ('350','19','綠島鄉','951'), ('351','19','蘭嶼鄉','952'),
    ('352','19','太麻里鄉','963'),
    # 澎湖縣 20
    ('353','20','馬公市','880'), ('354','20','湖西鄉','885'), ('355','20','白沙鄉','884'),
    ('356','20','西嶼鄉','881'), ('357','20','望安鄉','882'), ('358','20','七美鄉','883'),
    # 金門縣 21
    ('359','21','金城鎮','893'), ('360','21','金湖鎮','891'), ('361','21','金沙鎮','890'),
    ('362','21','金寧鄉','892'), ('363','21','烈嶼鄉','894'), ('364','21','烏坵鄉','896'),
    # 連江縣 22
    ('365','22','南竿鄉','209'), ('366','22','北竿鄉','210'),
    ('367','22','莒光鄉','211'), ('368','22','東引鄉','212'),
]

SERVICE_VENDORS = [
    # id, name, category, rating, phone, address, county_code, is_enable
    (1, '7-ELEVEN', '便利商店', 5.0, '0800-711711', '台北市大安區忠孝東路四段181號', '01', 1),
    (2, '萬家福',   '超市',     4.8, '02-2723-6789', '台北市信義區松高路1號B1', '01', 1),
    (3, '康是美',   '藥妝',     4.7, '02-2522-3333', '台北市中山區南京東路二段168號', '01', 1),
    (4, '統一生機', '有機食品', 4.6, '02-8712-4444', '台北市松山區八德路三段32號', '01', 1),
]

SERVICES = [
    (1, 1, '7-ELEVEN 商城購物',  '11', '統一超商 7-ELEVEN 健身商品線上採買服務', 1),
    (2, 2, '萬家福 商城購物',    '11', '萬家福超市健身食材採買服務',             1),
    (3, 3, '康是美 商城購物',    '11', '康是美藥妝保健品採買服務',               1),
    (4, 4, '統一生機 商城購物',  '11', '統一生機有機健康食品採買服務',           1),
]

FORMS = [
    (1, 1, '健身採買諮詢單', '填寫您的健身目標與採買需求，後台人員將主動聯繫安排採購配送。', 1),
]

FORM_GROUPS = [
    (1, 1, '基本資訊', 1),
    (2, 1, '採買需求', 2),
]

FORM_TOPICS = [
    (1, 1, 1, 3,  '健身目標',       '請選擇您的健身目標',             1, 1),
    (2, 1, 1, 1,  '採買預算（元）', '輸入本次採買的預算金額',         1, 2),
    (3, 1, 1, 10, '聯絡資料',       '方便後台人員與您聯繫',           1, 3),
    (4, 1, 2, 1,  '搜尋關鍵字',     '指定想找的商品名稱（選填）',     0, 1),
    (5, 1, 2, 2,  '特殊需求備註',   '例如：素食、過敏食材、指定品牌', 0, 2),
]

TOPIC_OPTIONS = [
    (1, 1, '增肌',     0, '', 1),
    (2, 1, '減脂',     0, '', 2),
    (3, 1, '維持體重', 0, '', 3),
    (4, 1, '搜尋商品', 0, '', 4),
]

# id, name, category, phone, address, county_code, rating, description, is_enable
PARTNER_VENDORS = [
    # 健身房（Being Sport — 統一集團旗下健身俱樂部）
    (1,  'Being Sport 信義店', '健身房', '02-2345-0001', '台北市信義區松高路11號',           '01', 4.9, 'Being Sport 旗艦店，多元精品課程，24小時智能門禁',     1),
    (2,  'Being Sport 大安店', '健身房', '02-2700-1234', '台北市大安區敦化南路一段100號',    '01', 4.8, '鄰近捷運，游泳池＋重訓室，專業教練常駐',               1),
    (3,  'Being Sport 板橋店', '健身房', '02-2987-5678', '新北市板橋區文化路二段25號',       '02', 4.7, '雙北最大 Being Sport 館，停車場免費，設備新穎',         1),
    (4,  'Being Sport 桃園店', '健身房', '03-3355-6677', '桃園市桃園區中正路88號',           '03', 4.6, '桃園地區旗艦館，大型有氧教室，提供兒童課程',           1),
    (5,  'Being Sport 台中店', '健身房', '04-2255-8888', '台中市西屯區文心路三段200號',      '04', 4.7, '台中核心地段，多間專業教室，課程種類最豐富',           1),
    # 餐廳
    (6,  '輕食廚房',          '餐廳',   '02-2321-8888', '台北市大安區和平東路一段45號',  '01', 4.7, '提供低卡高蛋白輕食套餐，適合健身族群，可線上訂餐',     1),
    (7,  '蛋白質料理坊',      '餐廳',   '02-2778-9999', '台北市信義區松仁路22號',         '01', 4.6, '專業健身餐盒，每日新鮮製作，提供增肌與減脂兩種菜單', 1),
    (8,  '健康滋味便當',      '餐廳',   '02-2200-3456', '新北市新店區中正路112號',        '02', 4.5, '均衡配餐，少油少鹽，提供外送服務，支援客製菜單',       1),
    (9,  '植物蛋白廚房',      '餐廳',   '04-2255-7788', '台中市西屯區文心路三段200號',    '04', 4.4, '以植物性食材為主，提供素食健身餐，富含植物蛋白',       1),
    # 搬家公司
    (10, '大榮搬家服務',      '搬家',   '02-2601-1111', '台北市中山區建國北路二段30號',   '01', 4.8, '專業搬家團隊，提供打包、搬運、組裝一條龍服務',         1),
    (11, '永安搬家公司',      '搬家',   '02-2900-2222', '新北市板橋區中山路一段50號',     '02', 4.6, '台北新北雙北地區配送，提供鋼琴、大型家具搬運',         1),
    (12, '快捷搬家服務',      '搬家',   '03-3568-3333', '桃園市中壢區中央西路一段80號',   '03', 4.5, '桃園地區搬家首選，費用透明，報價免費，服務有保障',     1),
    # 清潔公司
    (13, '舒潔居家清潔',      '清潔',   '02-2345-4444', '台北市大安區信義路三段60號',     '01', 4.9, '到府居家清潔，專業設備，可預約定期清潔，使用環保清潔劑', 1),
    (14, '快速清潔公司',      '清潔',   '02-2800-5555', '新北市中和區中正路100號',        '02', 4.7, '公寓、辦公室清潔，深層清潔，紗窗、冷氣、地板拋光',     1),
    (15, '亮潔家事服務',      '清潔',   '04-2358-6666', '台中市北屯區太原路三段180號',    '04', 4.6, '台中地區居家清潔，提供一次性與定期清潔方案',           1),
]

# id, gym_id, course_name, coach, course_type, weekday, time_start, duration_min,
#     max_slots, enrolled, price_month, month, min_students, status, is_enable
GYM_COURSES = [
    # Being Sport 信義店 (gym_id=1)
    (1,  1, '飛輪有氧訓練',   '陳教練', '有氧', '週一,週三,週五', '07:00', 45,  20, 15, 800,  '202607', 10, '已開課', 1),
    (2,  1, '核心肌群強化',   '林教練', '重訓', '週二,週四',      '18:30', 60,  15, 12, 900,  '202607', 10, '已開課', 1),
    (3,  1, '壺鈴功能訓練',   '王教練', '重訓', '週六',           '10:00', 60,  12, 10, 1000, '202607',  8, '已開課', 1),
    (4,  1, '哈他瑜珈初階',   '李教練', '瑜珈', '週二,週四',      '07:00', 60,  15, 15, 750,  '202607',  8, '已開課', 1),
    (5,  1, '有氧舞蹈 Zumba', '陳教練', '舞蹈', '週一,週三',      '19:00', 55,  20, 18, 850,  '202607', 10, '已開課', 1),
    # Being Sport 大安店 (gym_id=2)
    (6,  2, '拳擊有氧',       '張教練', '格鬥', '週一,週三,週五', '19:00', 50,  18, 14, 900,  '202607', 10, '已開課', 1),
    (7,  2, '重訓基礎入門',   '吳教練', '重訓', '週二,週六',      '10:00', 90,  10,  8, 1200, '202607',  6, '已開課', 1),
    (8,  2, '皮拉提斯',       '許教練', '瑜珈', '週三,週五',      '08:00', 60,  12, 11, 950,  '202607',  8, '已開課', 1),
    (9,  2, '泰拳訓練',       '黃教練', '格鬥', '週二,週四',      '20:00', 60,  15, 13, 1000, '202607', 10, '已開課', 1),
    (10, 2, 'TRX 懸吊訓練',   '吳教練', '重訓', '週六,週日',      '14:00', 60,  10,  9, 1100, '202607',  8, '已開課', 1),
    # Being Sport 板橋店 (gym_id=3)
    (11, 3, '晨間有氧操',     '鄭教練', '有氧', '週一至週五',     '06:30', 40,  25, 20, 600,  '202607', 12, '已開課', 1),
    (12, 3, '陰瑜珈放鬆',     '蔡教練', '瑜珈', '週三,週五',      '20:00', 75,  15, 14, 700,  '202607',  8, '已開課', 1),
    (13, 3, '自由重量訓練',   '鄭教練', '重訓', '週二,週四,週六', '17:00', 60,  12,  7, 800,  '202607',  8, '招生中', 1),
    # Being Sport 桃園店 (gym_id=4)
    (14, 4, '動感單車',       '游教練', '有氧', '週一,週三,週五', '18:00', 45,  20, 16, 750,  '202607', 10, '已開課', 1),
    (15, 4, '格鬥有氧 MMA',   '游教練', '格鬥', '週二,週六',      '19:30', 60,  15, 11, 900,  '202607', 10, '已開課', 1),
    (16, 4, '冥想瑜珈',       '謝教練', '瑜珈', '週日',           '09:00', 90,  15, 13, 650,  '202607',  8, '已開課', 1),
    # Being Sport 台中店 (gym_id=5) — 示範各種招生狀態
    (17, 5, '早晨瑜珈',       '吳教練', '瑜珈', '週一,週三,週五', '07:30', 60,  15,  9, 900,  '202607',  8, '已開課', 1),
    (18, 5, '核心強化訓練',   '陳教練', '重訓', '週二,週四',      '19:00', 60,  12,  7, 1000, '202607', 10, '招生中', 1),
    (19, 5, '有氧搏擊',       '林教練', '格鬥', '週三,週六',      '18:30', 50,  15,  8, 950,  '202607',  8, '招生中', 1),
    (20, 5, '重訓入門班',     '陳教練', '重訓', '週六,週日',      '10:00', 90,  10,  5, 1200, '202607', 12, '招生中', 1),
    (21, 5, '伸展放鬆課',     '吳教練', '瑜珈', '週五',           '21:00', 45,  20, 10, 650,  '202607',  6, '已開課', 1),
]

# id, course_id, feedback_no, contact_name, contact_phone, note, status, notified, enrolled_at
COURSE_ENROLLMENTS = [
    # Being Sport 早晨瑜珈 (course_id=17, enrolled=9, min=8, 已開課)
    (1,  17, '',  '王小明', '0912-111-001', '希望安排靠近門口的位置', '確認開課', 1, '2026-07-01T09:00:00'),
    (2,  17, '',  '李美玲', '0912-111-002', '',                       '確認開課', 1, '2026-07-01T10:30:00'),
    (3,  17, '',  '張志遠', '0912-111-003', '第一次上瑜珈課',         '確認開課', 1, '2026-07-02T08:00:00'),
    (4,  17, '',  '陳宜臻', '0912-111-004', '',                       '確認開課', 1, '2026-07-02T14:00:00'),
    (5,  17, '',  '林大衛', '0912-111-005', '有膝蓋舊傷',             '確認開課', 1, '2026-07-03T11:00:00'),
    (6,  17, '',  '黃雅婷', '0912-111-006', '',                       '確認開課', 1, '2026-07-03T16:00:00'),
    (7,  17, '',  '劉建豪', '0912-111-007', '',                       '確認開課', 1, '2026-07-04T09:00:00'),
    (8,  17, '',  '吳雅雯', '0912-111-008', '懷孕初期，需低強度',     '確認開課', 1, '2026-07-05T10:00:00'),
    (9,  17, '',  '蔡俊宏', '0912-111-009', '',                       '確認開課', 1, '2026-07-05T13:00:00'),
    # Being Sport 核心強化訓練 (course_id=18, enrolled=7, min=10, 招生中)
    (10, 18, '',  '許志豪', '0933-222-001', '',                       '報名中',   0, '2026-07-03T09:00:00'),
    (11, 18, '',  '余佩珊', '0933-222-002', '想加強腹部訓練',         '報名中',   0, '2026-07-04T10:00:00'),
    (12, 18, '',  '郭明哲', '0933-222-003', '',                       '報名中',   0, '2026-07-05T11:00:00'),
    (13, 18, '',  '謝淑芬', '0933-222-004', '',                       '報名中',   0, '2026-07-06T09:00:00'),
    (14, 18, '',  '洪建志', '0933-222-005', '有腰傷需告知教練',       '報名中',   0, '2026-07-07T14:00:00'),
    (15, 18, '',  '曾雅芳', '0933-222-006', '',                       '報名中',   0, '2026-07-08T10:00:00'),
    (16, 18, '',  '廖永祥', '0933-222-007', '',                       '報名中',   0, '2026-07-09T09:00:00'),
    # Being Sport 有氧搏擊 (course_id=19, enrolled=8, min=8, 招生中 → 剛好達標可開課)
    (17, 19, '',  '簡俊達', '0966-333-001', '',                       '報名中',   0, '2026-07-02T09:00:00'),
    (18, 19, '',  '蕭美玲', '0966-333-002', '',                       '報名中',   0, '2026-07-02T11:00:00'),
    (19, 19, '',  '鄭文豪', '0966-333-003', '要求安排較輕量練習',     '報名中',   0, '2026-07-03T09:00:00'),
    (20, 19, '',  '楊淑惠', '0966-333-004', '',                       '報名中',   0, '2026-07-04T10:00:00'),
    (21, 19, '',  '彭建明', '0966-333-005', '',                       '報名中',   0, '2026-07-05T09:00:00'),
    (22, 19, '',  '羅雅文', '0966-333-006', '',                       '報名中',   0, '2026-07-06T11:00:00'),
    (23, 19, '',  '江俊輝', '0966-333-007', '',                       '報名中',   0, '2026-07-07T09:00:00'),
    (24, 19, '',  '邱淑貞', '0966-333-008', '第一次上課',             '報名中',   0, '2026-07-08T14:00:00'),
    # Being Sport 重訓入門班 (course_id=20, enrolled=5, min=12, 招生中)
    (25, 20, '',  '葉志明', '0988-444-001', '',                       '報名中',   0, '2026-07-05T09:00:00'),
    (26, 20, '',  '施雅惠', '0988-444-002', '',                       '報名中',   0, '2026-07-06T10:00:00'),
    (27, 20, '',  '侯建宏', '0988-444-003', '想增肌減脂',             '報名中',   0, '2026-07-07T09:00:00'),
    (28, 20, '',  '沈美華', '0988-444-004', '',                       '報名中',   0, '2026-07-08T11:00:00'),
    (29, 20, '',  '卓永信', '0988-444-005', '',                       '報名中',   0, '2026-07-09T09:00:00'),
    # Being Sport 伸展放鬆課 (course_id=21, enrolled=10, min=6, 已開課)
    (30, 21, '',  '莊淑芳', '0911-555-001', '',                       '確認開課', 1, '2026-07-01T09:00:00'),
    (31, 21, '',  '蔣志豪', '0911-555-002', '',                       '確認開課', 1, '2026-07-01T11:00:00'),
    (32, 21, '',  '潘美珍', '0911-555-003', '需要低強度伸展',         '確認開課', 1, '2026-07-02T09:00:00'),
    (33, 21, '',  '馮建國', '0911-555-004', '',                       '確認開課', 1, '2026-07-03T10:00:00'),
    (34, 21, '',  '溫淑靜', '0911-555-005', '',                       '確認開課', 1, '2026-07-04T09:00:00'),
    (35, 21, '',  '袁俊偉', '0911-555-006', '',                       '確認開課', 1, '2026-07-05T11:00:00'),
    (36, 21, '',  '龍雅婷', '0911-555-007', '',                       '確認開課', 1, '2026-07-06T09:00:00'),
    (37, 21, '',  '方建成', '0911-555-008', '',                       '確認開課', 1, '2026-07-07T10:00:00'),
    (38, 21, '',  '安志遠', '0911-555-009', '辦公室久坐，需重點伸展', '確認開課', 1, '2026-07-08T09:00:00'),
    (39, 21, '',  '費淑芬', '0911-555-010', '',                       '確認開課', 1, '2026-07-09T11:00:00'),
]


def main():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.executescript(SCHEMA)

    cur.executemany(
        "INSERT INTO fitness_product "
        "(id,name,vendor,category,protein_g,calories,price,stock) VALUES (?,?,?,?,?,?,?,?)",
        PRODUCTS,
    )
    cur.executemany(
        "INSERT INTO sys_county (code,name) VALUES (?,?)",
        COUNTIES,
    )
    cur.executemany(
        "INSERT INTO sys_district (code,county_code,name,zip) VALUES (?,?,?,?)",
        DISTRICTS,
    )
    cur.executemany(
        "INSERT INTO cms_homepage_service_vendor "
        "(id,name,category,rating,phone,address,county_code,is_enable) VALUES (?,?,?,?,?,?,?,?)",
        SERVICE_VENDORS,
    )
    cur.executemany(
        "INSERT INTO cms_homepage_service "
        "(id,vendor_id,name,type,intro,is_enable) VALUES (?,?,?,?,?,?)",
        SERVICES,
    )
    cur.executemany(
        "INSERT INTO pms_form (id,service_id,name,intro_content,is_enable) VALUES (?,?,?,?,?)",
        FORMS,
    )
    cur.executemany(
        "INSERT INTO pms_form_group (id,form_id,name,sort) VALUES (?,?,?,?)",
        FORM_GROUPS,
    )
    cur.executemany(
        "INSERT INTO pms_form_topic "
        "(id,form_id,group_id,type,title,remark,is_required,sort) VALUES (?,?,?,?,?,?,?,?)",
        FORM_TOPICS,
    )
    cur.executemany(
        "INSERT INTO pms_topic_option (id,topic_id,option_name,unit_price,unit,sort) VALUES (?,?,?,?,?,?)",
        TOPIC_OPTIONS,
    )
    cur.executemany(
        "INSERT INTO partner_vendor "
        "(id,name,category,phone,address,county_code,rating,description,is_enable) VALUES (?,?,?,?,?,?,?,?,?)",
        PARTNER_VENDORS,
    )
    cur.executemany(
        "INSERT INTO gym_course "
        "(id,gym_id,course_name,coach,course_type,weekday,time_start,duration_min,"
        " max_slots,enrolled,price_month,month,min_students,status,is_enable) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        GYM_COURSES,
    )
    cur.executemany(
        "INSERT INTO course_enrollment "
        "(id,course_id,feedback_no,contact_name,contact_phone,note,status,notified,enrolled_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        COURSE_ENROLLMENTS,
    )
    con.commit()

    tables = [
        "fitness_product", "users", "sys_county", "sys_district",
        "cms_homepage_service_vendor", "cms_homepage_service",
        "pms_form", "pms_form_group", "pms_form_topic", "pms_topic_option",
        "pms_form_feedback", "mms_order_record",
        "partner_vendor", "gym_course", "course_enrollment",
    ]
    for t in tables:
        n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t:<32} {n} 筆")
    con.close()
    print(f"\n資料庫建立完成：{DB}")


if __name__ == "__main__":
    main()
