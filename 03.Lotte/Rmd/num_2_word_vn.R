library(dplyr)
library(stringr)
## Rewrite
to_9 <- c('không', 'một', 'hai', 'ba', 'bốn', 'năm', 'sáu','bảy', 'tám', 'chín')
tens <- c('mười','hai mươi', 'ba mươi', 'bốn mươi', 'năm mươi','sáu mươi', 'bảy mươi', 'tám mươi', 'chín mươi')
denom <- c('','nghìn', 'triệu','tỷ', 'nghìn tỷ', 'trăm nghìn tỷ')
## For number < 100
convert_nn <- function(x){
  n <- as.numeric(str_replace_all(x,",",""))
  so_tien <- case_when(
    (n < 10) ~ to_9[n+1],
    (n >= 10) ~ paste(tens[n%/%10],case_when(
      (n%%10) == 0 ~ "",
      (n%%10 == 1 & n%/%10 == 1) ~ 'một',
      (n%%10 == 1 & n%/%10 > 1) ~ 'mốt',
      (n%%10) == 5 ~ 'lăm',
      TRUE ~ to_9[n%%10+1] 
    )),
    TRUE ~ "N/A"
  )
  so_tien <- trimws(so_tien,which = "right")
  return(so_tien)
}
## For number < 1000
convert_nnn <- function(x){
  n <- as.numeric(str_replace_all(x,",",""))
  mod <- n%%100
  rem <- n%/%100
  
  so_tien <- case_when(
    (rem == 0) ~ convert_nn(n),
    (rem >= 1 & rem < 10) ~ paste(to_9[rem+1],"trăm",case_when(
      mod == 0 ~ "",
      (mod > 0 & mod < 10) ~ paste("lẻ",to_9[mod+1]),
      TRUE ~ convert_nn(mod)
    )),
    TRUE ~ "N/A"
  )
  so_tien <- trimws(so_tien,which = "right")
  return(so_tien)
}
## Combined Func
num_2_word_vn <- function(x){
  n <- as.numeric(str_replace_all(x,",",""))
  if (n < 100) return(convert_nn(n))
  else if (n < 10000) return(convert_nnn(n))
  else{
    i <- ((nchar(n) + 2) %/% 3) - 1
    lval <- n %/% (1000**i)
    r <- n - (lval * (1000**i))
    ret <- paste(convert_nnn(lval),denom[i+1])
    so_tien <- case_when(
      (r == 0) ~ paste0(ret),
      (r > 0 & r < 100) ~ paste(ret,"không trăm",convert_nn(r)),
      (r >= 100 & r < 1000) ~ paste(ret,convert_nnn(r)),
      (r >= 1000) ~ paste(ret,num_2_word_vn(r)),
      TRUE ~ "N/A")
    so_tien
  } 
}














