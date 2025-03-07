# -*- coding: utf-8 -*-


# Load model
from joblib import dump, load
# model_name = "DTR_model"
# model = load('../models/' + model_name + '.joblib')
# from datetime import datetime
# # model = load("DTR_model.joblib")

"""# Load CMEMS data
Try to use WMS or other more flexibel data retrieval
"""

import ftplib
import os
import numpy as np
import netCDF4 as nc
import pandas as pd
from datetime import datetime

def download(url, user, passwd, ftp_path, filename):
    
    with ftplib.FTP(url) as ftp:
        
        try:
            ftp.login(user, passwd)
            
            # Change directory
            ftp.cwd(ftp_path)
            
            # Download file (if there is not yet a local copy)
            if os.path.isfile(filename):
                print("There is already a local copy for this date ({})".format(filename))
            else:
                with open(filename, 'wb') as fp:
                    print("Downloading ... ({})".format(filename))
                    ftp.retrbinary('RETR {}'.format(filename), fp.write)
        
        except ftplib.all_errors as e:
            print('FTP error:', e)

# Check contents

"""
with ftplib.FTP('nrt.cmems-du.eu') as ftp:
    
    try:
        ftp.login(UN_CMEMS, PW_CMEMS)
        
        # Change directory
        ftp.cwd('Core/GLOBAL_ANALYSIS_FORECAST_PHY_001_024/global-analysis-forecast-phy-001-024/2021/07')
        
        # List directory contents with additional information
        ftp.retrlines('LIST') 
           
        # Get list of directory contents without additional information
        files = []
        ftp.retrlines('NLST', files.append) 
        print(files) 
        
        # Check file size
        print("{} MB".format(ftp.size('mfwamglocep_2020120100_R20201202.nc')/1000000))
            
    except ftplib.all_errors as e:
        print('FTP error:', e)
"""


def calc_relative_direction(ship_dir, ww_dir):
  """
  determine relative wind direction for ships going north, east, south or west

  Parameters
  ----------
  ship_dir : str, in ("N", "E", "S", "W")
    direction the ship is going
  ww_dir : array, float
    array of relative wind directions [0 - 360]
  """
  if ship_dir not in ("N", "E", "S", "W"):
    raise Exception("Direction not accepted.")
  ww_360 = ww_dir
  ww_360[ww_360 < 0] = 360 + ww_dir[0]
  if ship_dir in ("N"):
    dir_4 = np.full((len(ww_dir), 1), 2)
    dir_4[(ww_dir < 45) | (ww_dir > 315)] = 1
    dir_4[(ww_dir > 135) & (ww_dir < 225)] = 3
  if ship_dir in ("E"):
    dir_4 = np.full((len(ww_dir), 1), 2)
    dir_4[(ww_dir > 45) & (ww_dir < 135)] = 1
    dir_4[(ww_dir > 225) & (ww_dir < 315)] = 3
  if ship_dir in ("W"):
    dir_4 = np.full((len(ww_dir), 1), 2)
    dir_4[(ww_dir > 45) & (ww_dir < 135)] = 3
    dir_4[(ww_dir > 225) & (ww_dir < 315)] = 1
  if ship_dir in ("S"):
    dir_4 = np.full((len(ww_dir), 1), 2)
    dir_4[(ww_dir < 45) | (ww_dir > 315)] = 3
    dir_4[(ww_dir > 135) & (ww_dir < 225)] = 1
  return dir_4

def concatenate_cmems(cm_wave, cm_phy, ship_param, ship_dir):
  """
  concatenate the variables from cmems wave and physics datasets

  Parameters
  ----------
  cm_wave : net4CDF dataset
    netcdf file cmems wave
  cm_phy : net4CDF dataset
    netdcf file cmems physics
  ship_param : int
    ship variable that is used in model later (e.g. draft or length)
  ship_dir str, in ("N", "E", "S", "W")
    direction the ship is going
  """
  array = (np.flipud(cm_wave["VHM0"][0, :, :]).data) # extract data from CMEMS
  dim = array.shape
  l = np.prod(dim) # get number of "pixel"

  # extract parameters from cmems dataset and reshape to array with dimension of 1 x number of pixel
  vhm = (np.flipud(cm_wave["VHM0"][0, :, :])).reshape(l, 1)
  vtm = (np.flipud(cm_wave["VTPK"][0, :, :])).reshape(l, 1)
  temp = (np.flipud(cm_phy["thetao"][0, 1, :, :])).reshape(l, 1)
  sal = (np.flipud(cm_phy["so"][0, 1, :, :])).reshape(l, 1)
  # create column for ship parameter 
  ship = np.full((l, 1), ship_param) 
  # calculate relative direction of wind depending on ship direction
  dir = calc_relative_direction(ship_dir, (np.flipud(cm_wave["VMDR_WW"][0, :, :])).reshape(l, 1))

  # concatenate parameters
  a = np.concatenate((ship, vhm, vtm, temp, sal, dir), axis=1)

  # create pd df from array
  X_pred = pd.DataFrame(data=a,    # values
              index=list(range(0, l)),    # 1st column as index
              columns=["Draft", "VHM0", "VTPK", "thetao", "so", "dir_4"])  # 1st row as the column names
  return X_pred

def prepare_grid(cm_wave, cm_phy, ship_param, ship_dir, model):
  """
  prepare grid of SOGs

  Parameters
  ----------
  cm_wave : net4CDF dataset
    netcdf file cmems wave
  cm_phy : net4CDF dataset
    netdcf file cmems physics
  ship_param : int
    ship variable that is used in model later (e.g. draft or length)
  ship_dir str, in ("N", "E", "S", "W")
    direction the ship is going
  """

  X_pred = concatenate_cmems(cm_wave, cm_phy, ship_param, ship_dir)
  
  # extract shape from cmems data
  input = (np.flipud(cm_wave["VHM0"][0, :, :]))
  dim = input.shape

  # predict SOG
  # model = load('cms_routing/models/DTR_model.joblib') # import model
  SOG_pred = model.predict(X_pred)
  SOG_pred = SOG_pred.reshape(dim) # reshape to 'coordinates'
  SOG_pred[input < -30000] = -5 # -32767.0 # mask data with negative value

  return SOG_pred



def calculateTimeGrid(SOG_E, SOG_N, SOG_S, SOG_W, AOI):
    kmGridEW= np.load("lengthGridEW.npy")
    kmGridEW = kmGridEW[AOI[2]:AOI[3], AOI[0]:AOI[1]]
    kmGridNS= np.load("lengthGridNS.npy")
    kmGridNS = kmGridNS[AOI[2]:AOI[3], AOI[0]:AOI[1]]

    timeGridE = SOG_E
    constE= 70/np.power(timeGridE, 3)
    timeGridE80= np.cbrt(80/constE)
    timeGridE60= np.cbrt(60/constE)
    timeGridE = timeGridE[AOI[2]:AOI[3], AOI[0]:AOI[1]]
    timeGridE80 = timeGridE80[AOI[2]:AOI[3], AOI[0]:AOI[1]]
    timeGridE60 = timeGridE60[AOI[2]:AOI[3], AOI[0]:AOI[1]]
    timeGridE = np.where(timeGridE < 0, 10000, (kmGridEW*1000)/(timeGridE*30.87))
    timeGridE80 = np.where(timeGridE80 < 0, 10000, (kmGridEW*1000)/(timeGridE80*30.87))
    timeGridE60 = np.where(timeGridE60 < 0, 10000, (kmGridEW*1000)/(timeGridE60*30.87))



    timeGridN = SOG_N
    constN= 70/np.power(timeGridN, 3)
    timeGridN80= np.cbrt(80/constN)
    timeGridN60= np.cbrt(60/constN)
    timeGridN = timeGridN[AOI[2]:AOI[3], AOI[0]:AOI[1]]
    timeGridN80 = timeGridN80[AOI[2]:AOI[3], AOI[0]:AOI[1]]
    timeGridN60 = timeGridN60[AOI[2]:AOI[3], AOI[0]:AOI[1]]
    timeGridN = np.where(timeGridN < 0, 10000, (kmGridNS*1000)/(timeGridN*30.87))
    timeGridN80 = np.where(timeGridN80 < 0, 10000, (kmGridNS*1000)/(timeGridN80*30.87))
    timeGridN60 = np.where(timeGridN60 < 0, 10000, (kmGridNS*1000)/(timeGridN60*30.87))


    timeGridS = SOG_S
    constS= 70/np.power(timeGridS, 3)
    timeGridS80= np.cbrt(80/constS)
    timeGridS60= np.cbrt(60/constS)
    timeGridS = timeGridS[AOI[2]:AOI[3], AOI[0]:AOI[1]]
    timeGridS80 = timeGridS80[AOI[2]:AOI[3], AOI[0]:AOI[1]]
    timeGridS60 = timeGridS60[AOI[2]:AOI[3], AOI[0]:AOI[1]]
    timeGridS = np.where(timeGridS < 0, 10000, (kmGridNS*1000)/(timeGridS*30.87))
    timeGridS80 = np.where(timeGridS80 < 0, 10000, (kmGridNS*1000)/(timeGridS80*30.87))
    timeGridS60 = np.where(timeGridS60 < 0, 10000, (kmGridNS*1000)/(timeGridS60*30.87))




    timeGridW = SOG_W
    constW= 70/np.power(timeGridW, 3)
    timeGridW80= np.cbrt(80/constW)
    timeGridW60= np.cbrt(60/constW)
    timeGridW = timeGridW[AOI[2]:AOI[3], AOI[0]:AOI[1]]
    timeGridW80 = timeGridW80[AOI[2]:AOI[3], AOI[0]:AOI[1]]
    timeGridW60 = timeGridW60[AOI[2]:AOI[3], AOI[0]:AOI[1]]
    timeGridW = np.where(timeGridW < 0, 10000, (kmGridEW*1000)/(timeGridW*30.87))
    timeGridW80 = np.where(timeGridW80 < 0, 10000, (kmGridEW*1000)/(timeGridW80*30.87))
    timeGridW60 = np.where(timeGridW60 < 0, 10000, (kmGridEW*1000)/(timeGridW60*30.87))


    timeGrids=[[timeGridN80, timeGridS80, timeGridE80, timeGridW80],[timeGridN, timeGridS, timeGridE, timeGridW],[timeGridN60, timeGridS60, timeGridE60, timeGridW60]]
    return timeGrids



'''
# created masked array
import numpy.ma as ma
SOG_pred = np.ma.masked_where(np.flipud(np.ma.getmask(ds[parameter][0, :, :])), SOG_pred.reshape(dim))
SOG_pred.fill_value = -32767
# SOG_pred =np.flipud(SOG_pred)
'''

# # create actual grids for different ship directions
# ship_param = 12
# SOG_N = prepare_grid(model, ds, ds_p, ship_param, "N")
# SOG_E = prepare_grid(model, ds, ds_p, ship_param, "E")
# SOG_S = prepare_grid(model, ds, ds_p, ship_param, "S")
# SOG_W = prepare_grid(model, ds, ds_p, ship_param, "W")

# def cmems_paths(date):


def get_cmems(date_start, date_end, UN_CMEMS, PW_CMEMS):
    date_s = datetime.strptime(date_start, "%d.%m.%Y %H:%M")
    date_e = datetime.strptime(date_end, "%d.%m.%Y %H:%M")

    date_m = date_s + (date_e - date_s) / 2
    date = date_m.strftime("%Y%m%d")
    today = datetime.now().strftime("%Y%m%d")

    path_date = date[0:4] + "/" + date[4:6]
    url = 'nrt.cmems-du.eu'
    path_w = 'Core/GLOBAL_ANALYSIS_FORECAST_WAV_001_027/global-analysis-forecast-wav-001-027/' + path_date
    path_p = 'Core/GLOBAL_ANALYSIS_FORECAST_PHY_001_024/global-analysis-forecast-phy-001-024/' + path_date

    with ftplib.FTP(url) as ftp:
        try:
            ftp.login(UN_CMEMS, PW_CMEMS)
            ftp.cwd(path_w)
            files = ftp.nlst()
            files = [i for i in files if date in i]
            filename_w = files[0]
            ftp.cwd('/')
            ftp.cwd(path_p)
            files = ftp.nlst()
            files = [i for i in files if date in i]
            filename_p = files[0]
        except ftplib.all_errors as e:
            print('FTP error:', e)

    download(url, UN_CMEMS, PW_CMEMS, path_w, filename_w)
    download(url, UN_CMEMS, PW_CMEMS, path_p, filename_p)

    ds_w = nc.Dataset(filename_w)
    ds_p = nc.Dataset(filename_p)
    return (ds_w, ds_p)


""""
# set CMEMS credentials
UN_CMEMS = "jstenkamp"
PW_CMEMS = ""

# cmems wave data download
url = 'nrt.cmems-du.eu'
path = 'Core/GLOBAL_ANALYSIS_FORECAST_WAV_001_027/global-analysis-forecast-wav-001-027/2021/07'
filename = 'mfwamglocep_2021070200_R20210703.nc'
download(url, UN_CMEMS, PW_CMEMS, path, filename)

# cmems physics download
url = 'nrt.cmems-du.eu'
path = 'Core/GLOBAL_ANALYSIS_FORECAST_PHY_001_024/global-analysis-forecast-phy-001-024/2021/07'
filename_p = 'mercatorpsy4v3r1_gl12_mean_20210702_R20210703.nc'
download(url, UN_CMEMS, PW_CMEMS, path, filename_p)



# load files as netcdf dataset
ds = nc.Dataset(filename)
ds_p = nc.Dataset(filename_p)
# ds
"""
