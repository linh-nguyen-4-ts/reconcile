# recon eSignCLoud
rm(list=ls())
options(scipen = 999)
library(DBI)
library(bigrquery)
library(data.table)
library(lubridate)
library(magrittr)
library(tidyverse)
library(stringr)
library(RPostgreSQL)
library(stringi)
library(janitor)
library(readxl)
library(writexl)
library(RMySQL)
library(openxlsx)
library(dplyr)
library(googlesheets4) # to update goolesheet4 
library(googledrive) # upload files to google drive: 
library(openxlsx)

source('/home/trucnguyen/phone_prefix_change_func.R')

#doc application vao xem co phan tich ra duoc esign data k 
dj_con <- RMariaDB::dbConnect(drv=RMariaDB::MariaDB(),
                              host = 'dop-production-mysql-replica.ckzhnzkexzci.ap-southeast-1.rds.amazonaws.com',
                              dbname = "digital_journey",
                              user = "vn_da_dj_ro",
                              password = "AcToRtIolyMEMiCE",
                              port = '3306')

#recon_month = strftime( Sys.Date()-15,'%Y-%m')

query = paste0("select 
                       a1.id as application_id
                     , a1.lead_unique_token
                     , a1.lead_phone_number
                     , a1.lead_created_at
                     , a1.lead_client_code
                     , a1.id_number
                     , a1.other_id_number
                     , JSON_UNQUOTE( JSON_EXTRACT(a1.state_info, '$.state_track[0].at')) as app_onboarding_at
                     , e1.status
                     , e1.created_at as signed_at
                     , date_format(e1.created_at,'%Y-%m') as signed_month
               from esigns e1 left join applications a1
               on e1.application_id = a1.id
               where e1.status in ('signed', 'expired')
               and date_format(e1.created_at,'%Y-%m-%d') >= '2023-05-20' 
               and a1.lead_client_code = 'tpbank';")

tpb_esign_list <- dbGetQuery(dj_con, query) %>% data.table()

recon_month <- format(Sys.Date()-30,'%Y-%m')
start_recon <- floor_date(Sys.Date()-30,unit='month')
end_recon <- ceiling_date(Sys.Date()-30,unit = 'month')-1
path <- '/home/nhubui/tpb/'
#path2 = '/data-raw/vib/recon/esign/'

sub_fold = paste0(path,recon_month)
#sub_fold2 = paste0(path2,recon_month)

if (dir.exists(sub_fold2)==FALSE){
  dir.create(sub_fold2)
}

# data esign cua Tu Anh (gồm cả 2 status 'signed' và 'expired')
# vib_esign_list <- read.csv('/data-raw/vib/recon/esign/vib_esigns_list_2021-03.csv')
# file_list <- list.files('/data-raw/vib/recon/esign',pattern='vib_esigns_list',full.names = TRUE)
# n <- length(file_list)
# newest_file <- file_list[n]
# vib_esign_list <- read.csv(newest_file) %>% data.table() 
tpb_esign_list$lead_phone_number <- as.character(tpb_esign_list$lead_phone_number)

# các esign có status là ' signed'
ts_esign_list <- tpb_esign_list  %>% filter(status == 'signed')
expired <- tpb_esign_list %>% filter(status == 'expired') #0
tpb_esign_list %>% distinct(status)
tpb_esign_list %>% count(signed_month)

# lọc các phone có 2 lần ký trong db của TS
dup_ts_esign_list <- get_dupes(ts_esign_list, lead_phone_number)

# 1 phone có 2 token giống nhau và ký 2 lần => loại trùng
get_dupes(ts_esign_list,lead_unique_token) 
ts_esign_list %>% get_dupes(lead_unique_token)
ts_esign_list %<>% distinct(lead_phone_number, lead_unique_token, .keep_all = TRUE)

# data esign cua FPT gởi:
list.files(path = '/home/nhubui/tpb', pattern='TPBANK_', full.names = T) -> file_list

read_data <- function(fname) {
  read_xlsx(fname, sheet = 1, skip = 0) %>%
    mutate(month = substr(fname,25,31)) 
}

fpt_esigns_list = file_list[length(
  
)] %>% map_df(~read_data(.)) %>% data.table() %>% clean_names()
fpt_esigns_list %>% filter(is.na(phone_number)) 

#names(fpt_esigns_list)
fpt_esigns_list %<>% rename(lead_phone_number = phone_number) %>% mutate(#signed_month = as.Date(last_time_signing, '%Y-%m') |
                                                                         signed_month = substr(last_time_signing,1,7))
fpt_esigns_list %>% count(signed_month)
# TS ghi nhận nhưng FPT không:
anti_join(ts_esign_list, fpt_esigns_list, by = 'lead_phone_number') %>% count(signed_month)# %>% view() #26 T6
anti_join(ts_esign_list, fpt_esigns_list, by = 'lead_phone_number') 
tpb_esign_list %>% filter(lead_phone_number == '84932531939')

# FPT ghi nhận nhưng TS không:
anti_join(fpt_esigns_list, ts_esign_list,by = 'lead_phone_number') -> unmap # %>% view() #-> unmap #

tpb_esign_total <- file_list[1:(length(file_list)-1)] %>% map_df(~read_data(.)) %>% data.table() %>% clean_names()

tpb_esign_total %>% count(month)

tpb_esign_total %>% filter(phone_number %in% unmap$lead_phone_number) #0

vib_application %>% filter(lead_phone_number %in% unmap$lead_phone_number) #check tren application = phone -> lay application_id tra trong esigns 
# lead_phone_number application_id             state    status lead_unique_token lead_product_code lead_telco_code lead_score lead_source campaign_code
# 1       84933687466          50522           success reviewing          a4rQw4F5         vib_cc_01        mobifone    775-779         sms              
# 2       84932531939         543898           success    pushed          aRFSEya1         vib_cc_01        mobifone    788-788        grab  vib_duo_card
# 3       84933687466         581144 app_form.compound    pushed          YRFSN4Yj         vib_cc_01        mobifone                   grab  vib_duo_card
# status_at     lead_created_at     lead_expired_at      name phone_number
# 1 2020-11-09 11:00:17 2020-11-09 10:09:40 2020-12-09 23:59:59      v1.4  84933687466
# 2 2021-05-31 09:26:54 2021-05-31 08:45:25 2021-06-30 23:59:59 v1.2.grab  84932531939
# 3 2021-07-11 00:05:08 2021-06-10 07:51:26 2021-07-10 23:59:59 v1.2.grab  84933687466


unmap %>% select(c(1)) %>% view()


expired %>% filter(lead_phone_number %in% fpt_esigns_list$lead_phone_number) 
#        X lead_unique_token lead_phone_number     lead_created_at lead_client_code                   app_onboarding_at
# 1: 3024          eRFXkYYC       84912104194 2022-02-12 17:26:07   vib_score_card  2022-02-12T17:26:07.37103932+07:00
# 2: 6807          UiKvZUbY       84346406440 2022-02-22 18:37:32   vib_score_card  2022-02-22T18:37:32.205610668+07:00
# status           signed_at signed_month
# 1: expired 2022-02-16 09:14:48      2022-02
# 2: expired 2022-02-22 18:45:06      2022-02

fpt_esigns_list %>% filter(lead_phone_number %in% unmap$lead_phone_number) %>% select(-signed_month) %>% view()

# lọc các phone có 2 lần ký trong db của TS
dup_fpt_esigns_list <- get_dupes(fpt_esigns_list, lead_phone_number)

anti_join(dup_ts_esign_list, dup_fpt_esigns_list, by = 'lead_phone_number') 
anti_join(dup_fpt_esigns_list, dup_ts_esign_list, by = 'lead_phone_number') 

write.csv(ts_esign_list,paste0(sub_fold2,'/esign_check_',recon_month,'.csv'),row.names = FALSE)
write.xlsx(ts_esign_list,paste0(sub_fold,'/esign_check_',recon_month,'.xlsx'),row.names = FALSE)

#check data esign gui 
names(fpt_esigns_list)
min(fpt_esigns_list[which(!is.na(fpt_esigns_list$signed_month)),]$signed_month)


#thu query thoi gian rong hon de xem co bi lay thieu k va check xem unique_token tren application ghi nhan la gi 



