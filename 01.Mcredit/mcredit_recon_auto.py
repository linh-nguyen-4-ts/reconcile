#%%
import sys
# sys.path.append("/home/baokhanh/")
import pandas as pd
import numpy as np
import os
import calendar
import psycopg2
from pathlib import Path
from loguru import logger
from dotenv import load_dotenv
from datetime import datetime, timedelta
from unidecode import unidecode
from avay_bq import AvayBQServiceAcc

from da_utils.client.google_sheets_client import GoogleSheetsClient
from da_utils.repository.google_sheets.google_sheets_repository import GoogleSheetsService

from da_utils.client.gmail_client import GmailClient
from da_utils.repository.gmail.gmail_repository import GmailRepository
from da_utils.repository.gmail.custom_types import GmailMessage

from da_utils.client.drive_client import GoogleDriveClient
from da_utils.repository.drive.drive_repository import GoogleDriveService

from da_utils.client.slack_client import SlackClient
from da_utils.repository.slack.slack_repository import SlackRepository

load_dotenv()
pd.options.display.max_columns = None
pd.options.display.max_colwidth = 2000


#%%
gmail_client = GmailClient(Path(os.environ.get("GOOGLE_CREDENTIALS_PATH")), Path(os.environ.get("GMAIL_TOKEN_PATH")))
gmail_repo = GmailRepository(gmail_client)

drive_client = GoogleDriveClient( )
drive_repo = GoogleDriveService(drive_client)

ggsheet_client = GoogleSheetsClient( )
ggsheet_repo = GoogleSheetsService(ggsheet_client)

slack_client = SlackClient(token=os.environ.get("SLACK_BOT_AUTHEN"))
slack_repo = SlackRepository(client=slack_client)

conn = psycopg2.connect(
    host = "v1proxy-new-postgres-replica.cvhqeqp3dmlv.ap-southeast-1.rds.amazonaws.com",
    dbname = "score_api_production",
    user = "analytic",
    password = "COng@tr0ngcuctacuctac",
    port = "5432"
)

#%%
def dayrange_recon(day_from_curr: int = 25) -> tuple:
    curr_time = datetime.now()
    recon_time =(curr_time - timedelta(day_from_curr))
    _, end_date = calendar.monthrange(int(recon_time.strftime("%Y")), int(recon_time.strftime("%m")))

    recon_month = recon_time.strftime("%m-%Y")
    month = recon_time.strftime("%Y-%m")
    start_date = recon_time.strftime("%Y-%m") + "-" + "01"
    end_date = recon_time.strftime("%Y-%m") + "-" + str(end_date)
    return recon_month, month, recon_time, start_date, end_date

recon_month, month, recon_time, start_date, end_date = dayrange_recon()
# %%
#1.1 Get file from gmail 

date_str = "{}/{}".format(recon_time.month, recon_time.year)
QUERY_STRING=f'"[TS - Mcredit] Leadgen Service Reconciliation {month}"'
CLIENT_EMAIL="duongntt.ts@mcredit.com.vn"
SNIPPET = f"MC gửi đối soát phí dịch vụ Leadgen tháng {date_str}"
# print(QUERY_STRING)

gmail_messages = gmail_repo.search_messages_by_query(query=QUERY_STRING)
gmail_messages_list: list[GmailMessage] = []

def id(message):
    x=""
    for message in gmail_messages:
        if SNIPPET in message.snippet:
            x = message.id
    return x

gmail_repo.query_attachments_from_email_message(gmail_repo.get_message_by_id(id(gmail_messages)))


file_path = gmail_repo.download_attachments(
    attachment_list= gmail_repo.query_attachments_from_email_message(
        gmail_repo.get_message_by_id(id(gmail_messages))
        ),
    parent_folder=Path('/home/linhnguyen/04.Reconcile/01.Mcredit/00.dataraw')
)
#%%
#1.2 Read and clean file 

df = pd.read_excel(Path(str(file_path[0])))#, header = 10)
df.dropna(how='all', inplace=True)
def clean_names(df):
    df.columns = df.columns.str.lower()
    df.columns = df.columns.str.replace(' ', '_')
    df.columns = df.columns.str.replace('[^\w\s]', '')
    df.columns = df.columns.map(lambda x: unidecode(x))
    return df

clean_names(df)

#%%
df = df[['ngay_gui_data', 'dia_chi', 'doanhso', 'hoahong', 'ma_san_pham', 'ngay_gn', 'so_hop_dong', 'lead_id']]
df.columns = ['sent_date', 'address', 'la', 'commission', 'product_name', 'disbursed_date', 'so_hop_dong', 'lead_id']

df = df.astype({'sent_date': str, 'disbursed_date': str})

df['disbursed_month'] = df['disbursed_date'].str.slice(stop=7)
df['batch_month'] = df['sent_date'].str.slice(stop=7)
df['sent_date'] = df['sent_date'].str.slice(stop=10)

df['product_name'].unique()

#%% 
#2. Data TS
query = """
SELECT DISTINCT
    id as lead_id, 
    phone_number, 
    bank_code,
    bound_code, 
    score, 
    score_range,
    to_char(sent_at AT TIME ZONE 'UTC','YYYY-MM-DD') as sent_date,
    to_char(sent_at AT TIME ZONE 'UTC','YYYY-MM') as batch_month,
    (case when (other ->> 'sender')::text is null and (other ->> 'channel')::text is null then 'sms' 
        when (other ->> 'sender')::text = 'sms' then 'sms'
        when (other ->> 'sender')::text = 'avay' then 'avay' 
        when (other ->> 'sender')::text = 'viet_tin' then 'viet_tin' 
        end) as channel, 
    (other ->> 'province') as location,
    (case when (pre_scoring_data ->> 'is_qualified')::boolean = true then 1 else 0 end) as qualified,
    (other ->> 'id_card_number') as nid, 
    telco_code,
    was_sent
FROM phone_infos 
WHERE 
    bank_code = 'mcredit'
"""

sent_leads = pd.read_sql(query, conn)

#%%
sent_leads['score'] = sent_leads.apply(lambda x: x['score'] if pd.notna(x['score']) else x['score_range'][0:3], axis=1)
sent_leads = sent_leads.astype({'lead_id': int, 'score': int})

sent_leads['new_bound_code'] = np.select(
    [
        (sent_leads['score'] >= 550) & (sent_leads['score'] <= 585),
        (sent_leads['score'] >= 586) & (sent_leads['score'] <= 625),
        (sent_leads['score'] >= 626),
        (sent_leads['score'] < 0),
        (sent_leads['score'] < 550) & (sent_leads['score'] >= 0)
    ],
    [
        'VT60',
        'VT47',
        'VT37',
        'NO-SCORE',
        're-check'
    ],
    default=np.nan
)

sent_leads = sent_leads.astype({'new_bound_code': str})
#%%
# 3. JOINING 2 DATA SOURCES
mc_disbursed_join = pd.merge(df, 
                             sent_leads[['batch_month', 'sent_date', 'phone_number', 'new_bound_code', 
                                      'nid', 'channel', 'telco_code', 'lead_id', 'score']].drop_duplicates(),
                             on=['lead_id', 'sent_date'], 
                             suffixes=('_MC', '_TS'), 
                             how='inner')

if mc_disbursed_join.loc[mc_disbursed_join['new_bound_code'].isna(), :].empty:
    print('There is no NA new_bound_code')
else:
    num_rows = len(mc_disbursed_join) - len(mc_disbursed_join.loc[mc_disbursed_join['new_bound_code'].isna(), :])
    print(f'There is {num_rows} NA new_bound_code')
# create a dictionary to map product names to new_bound_code values
product_map = {'CS RL LG TS 37': 'VT37',
               'CS RL LG TS 47': 'VT47',
               'CS RL LG TS 60': 'VT60'}

# map the product_name values to new Bound Code using the dictionary
mc_disbursed_join['product_name_MC'] = np.where(mc_disbursed_join['product_name'].isin(product_map.keys()), 
                                                 mc_disbursed_join['product_name'].map(product_map), 
                                                 'NO-SCORE')

#%%
# filter rows where new_bound_code is equal to product_name_MC
mc_disbursed_join1 = mc_disbursed_join[mc_disbursed_join['new_bound_code'] == mc_disbursed_join['product_name_MC']][['sent_date', 'address', 'la','commission', 'product_name',
                                                                                                                      'disbursed_date', 'so_hop_dong', 'lead_id',
                                                                                                                      'disbursed_month', 'batch_month_MC', 'phone_number',
                                                                                                                      'score', 'channel', 'nid', 'telco_code', 'new_bound_code']]
mc_disbursed_join1
#%%
# filter rows where new_bound_code is NOT equal to product_name_MC
mc_disbursed_join2 = mc_disbursed_join[mc_disbursed_join['new_bound_code'] != mc_disbursed_join['product_name_MC']]
mc_disbursed_join2.head()

#%%
# join mc_disbursed_join2 with mc_sent on phone_number column
lead_check = pd.merge(mc_disbursed_join2.drop('new_bound_code', axis=1),
                      sent_leads[['lead_id', 'phone_number', 'new_bound_code', 'sent_date', 'score', 'channel']],
                      how='left', 
                      on=['phone_number'], 
                      suffixes=('_MC', '_TS'))
lead_check.rename(columns = {'channel_TS':'channel'}, inplace = True)
# arrange by `sent_date_TS` column
lead_check = lead_check.sort_values(by='sent_date_TS')

# group by `phone_number` and add a `sent_order` column
lead_check['sent_order'] = (lead_check['phone_number'].notna()).groupby(lead_check['phone_number']).cumsum()

# get max sent_order value for each phone_number
max_sent_order = lead_check.groupby('phone_number')['sent_order'].max().reset_index()

# filter lead_check to keep only the rows with max sent_order
lead_check_max_order = pd.merge(lead_check, max_sent_order, on=['phone_number', 'sent_order'])

# drop the `sent_order` column
lead_check_max_order = lead_check_max_order.drop(columns=['sent_order'])

# select columns for mc_disbursed_join2
mc_disbursed_join2 = lead_check_max_order[['sent_date_TS', 'address', 'la', 'commission', 'product_name', 'disbursed_date', 'so_hop_dong', 'lead_id_TS',
  'disbursed_month', 'batch_month_MC', 'phone_number', 'score_TS', 'channel', 'nid', 'telco_code', 'new_bound_code']].\
    rename(columns={'sent_date_TS': 'sent_date', 'lead_id_TS': 'lead_id' , 'score_TS': 'score'})


# merge mc_disbursed_join1 and mc_disbursed_join2 before removing duplicates
mc_disbursed_join = pd.concat([mc_disbursed_join1, mc_disbursed_join2]).drop_duplicates()

#%%
from functools import reduce

# create the `price` column for `mc_disbursed_join`
mc_disbursed_join['price'] = pd.Series(
    np.where(mc_disbursed_join['new_bound_code'] != 'NO-SCORE', 0.05 * mc_disbursed_join['la'], 0.012 * mc_disbursed_join['la']),
    index = mc_disbursed_join.index
)

# group by `product_name` and `new_bound_code` columns and summarize the data
grouped_data = mc_disbursed_join.groupby(['new_bound_code','product_name']).agg(
    disbursed_lead = ('lead_id', 'count'),
    Loan_disbursed = ('la', 'sum'),
    Fee_re_calculate = ('price', 'sum'),
    Fee_non_VAT = ('commission', 'sum'),
    Fee_inc_VAT = ('commission', lambda x: x.sum() * 1.1)
)

# create the `check` column
grouped_data['check'] = grouped_data['Fee_re_calculate'] - grouped_data['Fee_non_VAT']

# add a total row and format the numeric columns
grouped_data = pd.concat([grouped_data, grouped_data.agg(['sum'])])
grouped_data = grouped_data.applymap('{:,.2f}'.format)

# remove the index name
grouped_data.index.names = [None]

# display the resulting dataframe
grouped_data

#%% SUMMARY FILE AND UPLOAD TO GDRIVE
grouped_data = mc_disbursed_join.groupby(['new_bound_code'], as_index=False).agg(
    disbursals = ('lead_id', 'count'),
    Loan_disbursed = ('la', 'sum'),
    Fee_non_VAT = ('commission', 'sum'),
    Fee_inc_VAT = ('commission', lambda x: x.sum() * 1.1)
)

# add a total row to the resulting dataframe
grouped_data = pd.concat([grouped_data, grouped_data.agg(['sum'])])

# remove the index name
grouped_data.index.names = [None]

path = '/home/linhnguyen/04.Reconcile/01.Mcredit/'
file_sum = f'{path}{month}/summary_{month}.xlsx'

# Create the directory if it does not already exist
if not os.path.exists(f'{path}{month}'):
    os.makedirs(f'{path}{month}')

grouped_data.to_excel(file_sum, index=False)
#%%
#UPLOAD
parent_folder_id = '19Y0Fp0FFIac83kwauu0GGJoJkcXAtZxl'
folder_check = drive_repo.list_folder_names(parent_folder_id =  parent_folder_id)

if month not in folder_check:
        folder_id = drive_repo.create_folder(folder_name= month, parent_folder_id =  parent_folder_id)
else:
        folder_id = drive_repo.get_folders(folder_name= month, parent_folder_id =  parent_folder_id)

sheet_check = drive_repo.list_file_names(parent_folder_id= folder_id[0])

if "summary_" + recon_month not in sheet_check: 
        summary_wb = ggsheet_repo.create_spreadsheet(spreadsheet_name = "summary_" + recon_month,parent_folder_id = folder_id[0])
        summary_ws = summary_wb.worksheet('Sheet1')
        ggsheet_repo.write_df_to_sheet(worksheet = summary_ws, df_to_write = grouped_data, starting_cell='A1')
else:
        spreadsheet_key = drive_repo.get_files(file_name = "summary_" + recon_month,parent_folder_id = folder_id[0])
        summary_wb = ggsheet_repo.open_spreadsheet(spreadsheet_key = spreadsheet_key, folder_id = folder_id)
        summary_ws = summary_wb.worksheet('Sheet1').clear()
        ggsheet_repo.write_df_to_sheet(worksheet = summary_ws, df_to_write = grouped_data, starting_cell='A1')


#%% UPDATE DISBURSAL
from google.cloud import bigquery
from google.oauth2 import service_account

avay_bq_acc = AvayBQServiceAcc()

avay_df = avay_bq_acc.client.query(f"""
select case when source = 'prod.sendo' then 'Sendo'
        when source = 'prod.chotot' then 'ChoTot'
        when source = 'prod.kalapa' then 'Kalapa'
        when source = 'prod.vpp.viettel' then 'Viettel Pay Pro'
        when source = 'prod.vtp.viettel' then 'Viettel Pay'
        when utm_source like 'dir%' then utm_source
        when source = 'vaycucde.vn' then 'Vaycucde'
        when utm_source = 'fimar' then 'Fimar'
        when utm_source like '%ccesstra%' then 'Accesstrade'
        when utm_source = 'masoffer' then 'Masoffer'
        when utm_source = 'vaysieude' then 'Vaysieude'
        when utm_source = 'thomaytaichinh' then 'Thomaytaichinh'
        when utm_source = 'adpia' THEN 'Adpia'
        when utm_source like '%acebook%' or utm_source like '%fb%' or utm_source like 'chatfuel%' then 'Facebook'
        when source = 'android_app' then 'Android App'
        when utm_campaign = 'adtima' or utm_source like 'zal%' then 'Zalo'
        when utm_source = 'sales_doubler' then 'Sale Doubler'
        when source = 'prod.zalo' then 'Zalo CC'
        when utm_source like 'google_ad%' then 'Google ads'
        when utm_source = 'zns' then 'ZNS'
        when utm_source = 'mpcc' then 'mpcc'
        when utm_source like 'mgi%' then 'MGID'
        when utm_source = 'fingo' then 'Fingo'
        when utm_source = 'esmart' then 'eSmart'
        when utm_source = 'linh_dan_spa' then 'Linh Dan Spa'
        when utm_source = 'cafe_anh' then 'Cafe Anh'
        when utm_source = 'tanvd' then 'Tanvd'
        when utm_source = 'adfly' then 'Adfly'
        when utm_source = 'coccoc' then 'Coccoc'
        when utm_source in ('adskeeper','adskeeper.com') then 'Adskeeper'
        when utm_source = 'vinfin' then 'Vinfin'
        when utm_source = 'propellerads' then 'Propellerads'
        when utm_source = 'dinos' then 'Dinos'
        when utm_source = 'clickadu' then 'Clickadu'
        else 'Others' end as lead_source
    ,lead_id
  from `avay-a9925.dwh.loans` l
  left join `avay-a9925.dwh.registrations` r on r.id = l.reg_id
  left join `avay-a9925.dwh.otps` o on r.otp_id = o.id
  where l.lead_id is not null
                          ;""").result().to_arrow().to_pandas()
  
avay_df

#%%
def process_mc_disbursed_join(mc_disbursed_join):
    
    # create a copy of the mc_disbursed_join dataframe
    mc_disbursed_to_write = mc_disbursed_join.copy()

    # perform data transformations
    mc_disbursed_to_write['bank_code'] = 'mcredit'
    mc_disbursed_to_write['lead_id'] = mc_disbursed_to_write['lead_id'].astype(int)
    mc_disbursed_to_write['phone_number'] = mc_disbursed_to_write['phone_number'].astype(str)
    mc_disbursed_to_write['batch_date'] = mc_disbursed_to_write['sent_date'].astype(str)
    mc_disbursed_to_write['channel'] = mc_disbursed_to_write['channel'].astype(str)
    mc_disbursed_to_write['product_code'] = mc_disbursed_join['new_bound_code'].astype(str)
    mc_disbursed_to_write['nid'] = np.nan
    mc_disbursed_to_write['telco_code'] = mc_disbursed_to_write['telco_code'].astype(str)
    mc_disbursed_to_write['tenor'] = np.nan
    mc_disbursed_to_write['loan_amount'] = mc_disbursed_join['la'].astype(float)
    mc_disbursed_to_write['fee_level'] = 0.05
    mc_disbursed_to_write['commission'] = mc_disbursed_join['commission']
    mc_disbursed_to_write['disbursed_date'] = mc_disbursed_join['disbursed_date'].astype(str)

    # select the columns to keep
    mc_disbursed_to_write = mc_disbursed_to_write[['bank_code', 'lead_id', 'phone_number', 'batch_date', 'channel', 'product_code', 'nid', 'telco_code', 'tenor', 'loan_amount', 'disbursed_date', 'fee_level', 'commission']]

    # convert the dataframe to data.table format
    mc_disbursed_to_write = mc_disbursed_to_write.to_dict('list')
    mc_disbursed_to_write = {key: pd.Series(value) for key, value in mc_disbursed_to_write.items()}
    mc_disbursed_to_write = pd.DataFrame(mc_disbursed_to_write)
    mc_disbursed_to_write = mc_disbursed_to_write.to_records(index=False)
    mc_disbursed_to_write = pd.DataFrame(mc_disbursed_to_write)
    
    return mc_disbursed_to_write

mc_disbursed_to_write = process_mc_disbursed_join(mc_disbursed_join)

mc_disbursed_to_write.head()

#%%
# perform left join on mc_disbursed_to_write and lead_source dataframes
mc_disbursed_to_write_new = pd.merge(mc_disbursed_to_write, avay_df,
 how='left', 
 left_on='lead_id', 
 right_on='lead_id', 
 left_index=False, 
 right_index=False, 
 sort=False, 
 suffixes=('_mc', '_avay'))

file_disbursed = f'{path}{month}/mcredit_disbursed_{month}.xlsx'
file_disbursed_stored = f'{path}{month}/mcredit_disbursed_{month}.csv'

mc_disbursed_to_write_new.to_excel(file_disbursed, index=False)
mc_disbursed_to_write_new.to_csv(file_disbursed_stored, index=False)

#%% NOTI ON SLACK
from slack import WebClient
from slack.errors import SlackApiError

bot_auth_token = os.environ.get("SLACK_BOT_AUTHEN")
user_auth_token = os.environ.get("SLACK_USER_AUTHEN")

clientSlack = WebClient(token = bot_auth_token)

channel_id = "C04MYU3L7LN"
user_id = "U0480LX5468"
linh_id = "U047QMYB9TQ"

file_path: Path = Path(file_disbursed_stored)

# Send success message to channel
clientSlack.chat_postMessage(**{"text": f"<@{user_id}> update disbursals MCredit {recon_month} cc:"'<@'+linh_id+'>'} , channel=channel_id)

# Upload file to channel
filetype = file_path.suffix[1:]
filename = file_path.name
with open(file_path, "rb") as file:
	clientSlack.files_upload(channels=channel_id, file=file, title=filename, filetype=filetype)
#%% CREATE DETAIL FILE FOR RMARKDOWN
mc_disbursed_join['sender'] = np.where(mc_disbursed_join['channel'] == 'avay', 'AVAY',
                                       np.where((mc_disbursed_join['telco_code'] == 'viettel') & (mc_disbursed_join['channel'] == 'sms'), 'VIETTEL',
                                                np.where((mc_disbursed_join['telco_code'] == 'mobifone')& (mc_disbursed_join['channel'] == 'sms'), 'MOBIFONE', 're-check')))

detail = mc_disbursed_join[['lead_id','sent_date','disbursed_date', 'channel','sender','product_name','so_hop_dong','la', 'commission']]

if "detail_leads_" + month not in sheet_check:
        detail_wb = ggsheet_repo.create_spreadsheet(spreadsheet_name = "detail_leads_" + recon_month, parent_folder_id= folder_id[0])
        detail_ws = detail_wb.worksheet('Sheet1')
        ggsheet_repo.write_df_to_sheet(worksheet = detail_ws, df_to_write = detail, starting_cell='A1')
else:
        spreadsheet_key = drive_repo.get_files(file_name = "detail_leads_" + recon_month,parent_folder_id = folder_id[0])
        detail_wb = ggsheet_repo.open_spreadsheet(spreadsheet_key = spreadsheet_key, folder_id = folder_id)
        detail_ws = detail_wb.worksheet('Sheet1').clear()
        ggsheet_repo.write_df_to_sheet(worksheet = detail_ws, df_to_write = detail, starting_cell='A1')
#%%

# rename columns and select required columns from detail dataframe
local_path = f'{path}{month}/'

print_df = detail.rename(columns={
    'lead_id': 'LEAD_ID', 
    'sent_date': 'DATE',
    'product_name': 'TEN_SP',
    'so_hop_dong': 'SO_HOP_DONG', 
    'commission': 'COMMISION'
})[['LEAD_ID', 'DATE', 'TEN_SP', 'SO_HOP_DONG', 'COMMISION']]
    
# filter cases of NO-SCORE and SCORE into separate dataframes
df_score = print_df[print_df['TEN_SP'].isin(['CS LG TS 37', 'CS LG TS 60', 'CS LG TS 47',
                                            'CS RL LG TS 37', 'CS RL LG TS 47', 'CS RL LG TS 60', 'AFC'])]

df_no_score = print_df[print_df['TEN_SP'].isin(['CS RL SCO TS MOBI 37', 
                                               'CS RL SCO TS MOBI 47', 
                                               'CS RL SCO TS 37', 
                                               'CS RL BHYT 47', 
                                               'CS RL CF A 50', 
                                               'CS CF C 45', 
                                               'CS CF A 50', 
                                               'CS RL CF C 45'])]

# display the dimensions of the resultant dataframes
print(df_no_score.shape)
print(df_score.shape)

# save the two dataframes to CSV files
df_score.to_csv(local_path + '/df_score.csv', index=False)
df_no_score.to_csv(local_path + '/df_no_score.csv', index=False)
# %%
