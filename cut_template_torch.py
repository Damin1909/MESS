""" Cut template waveform with Pytorch (preprocess in cut)
  Inputs
    data_dir: dir of continuous data
    temp_pha: template phase file
    out_root: root dir for template data
  Outputs
    temp_root/temp_name/net.sta.chn
    Note: temp_name == ot (yyyymmddhhmmss.ss)
"""
import os, sys, glob, shutil
sys.path.append('/home/zhouyj/software/data_prep')
import argparse
import numpy as np
import torch.multiprocessing as mp
from torch.utils.data import Dataset, DataLoader
from obspy import read, UTCDateTime
import sac
from dataset_gpu import read_ftemp, preprocess
import config
import warnings
warnings.filterwarnings("ignore")

# cut params
cfg = config.Config()
num_workers = cfg.num_workers
win_len = cfg.win_len 
get_data_dict = cfg.get_data_dict


def get_sta_date(event_list):
    sta_date_dict = {}
    for i, [id_name, event_loc, pick_dict] in enumerate(event_list):
        if i%1e3==0: print('%s/%s events done/total'%(i, len(event_list)))
        # 1. get event info
        event_name = id_name.split('_')[1]
        event_dir = os.path.join(args.out_root, event_name)
        ot = event_loc[0]
        if not os.path.exists(event_dir): os.makedirs(event_dir)
        for net_sta, [tp, ts] in pick_dict.items():
            date = str(tp.date)
            sta_date = '%s_%s'%(net_sta, date) # for one day's stream data
            if sta_date not in sta_date_dict:
                sta_date_dict[sta_date] = [[event_dir, tp, ts]]
            else: sta_date_dict[sta_date].append([event_dir, tp, ts])
    return sta_date_dict


class Cut_Templates(Dataset):
  """ Dataset for cutting templates
  """
  def __init__(self, sta_date_items):
    self.sta_date_items = sta_date_items
    self.data_dir = args.data_dir

  def __getitem__(self, index):
    data_paths_i = []
    # get one sta-date
    sta_date, samples = self.sta_date_items[index]
    net_sta, date = sta_date.split('_')
    net, sta = net_sta.split('.')
    date = UTCDateTime(date)
    # read & prep one day's data
    print('reading %s %s'%(net_sta, date.date))
    data_dict = get_data_dict(date, self.data_dir)
    if net_sta not in data_dict: return data_paths_i
    st_paths = data_dict[net_sta]
    try:
        stream  = read(st_paths[0])
        stream += read(st_paths[1])
        stream += read(st_paths[2])
    except: return data_paths_i
    stream = preprocess(stream)
    if len(stream)!=3: return data_paths_i
    for [event_dir, tp, ts] in samples:
        # time shift & prep
        start_time = tp - win_len[0]
        end_time = tp + win_len[1]
        st = sac.obspy_slice(stream, start_time, end_time)
        if 0 in st.max() or len(st)!=3: continue
        st = st.detrend('demean')  # note: no detrend here
        # write & record out_paths
        data_paths_i.append([])
        for tr in st:
            out_path = os.path.join(event_dir,'%s.%s'%(net_sta,tr.stats.channel))
            tr.stats.sac.t0, tr.stats.sac.t1 = tp-start_time, ts-start_time
            tr.write(out_path, format='sac')
            data_paths_i[-1].append(out_path)
    return data_paths_i

  def __len__(self):
    return len(self.sta_date_items)


if __name__ == '__main__':
    mp.set_start_method('spawn', force=True) # 'spawn' or 'forkserver'
    parser = argparse.ArgumentParser()
    parser.add_argument('--data_dir', type=str,
                        default='/data/Example_data')
    parser.add_argument('--temp_pha', type=str,
                        default='input/example.temp')
    parser.add_argument('--out_root', type=str,
                        default='output/example_templates')
    args = parser.parse_args()

    # read fpha
    temp_list = read_ftemp(args.temp_pha)
    sta_date_dict = get_sta_date(temp_list)
    sta_date_items = list(sta_date_dict.items())
    # for sta-date pairs
    data_paths  = []
    dataset = Cut_Templates(sta_date_items)
    dataloader = DataLoader(dataset, num_workers=num_workers, batch_size=None)
    for i, data_paths_i in enumerate(dataloader): 
        data_paths += data_paths_i
        if i%10==0: print('%s/%s sta-date pairs done/total'%(i+1,len(dataset)))
    fout_data_paths = os.path.join(args.out_root,'data_paths.npy')
    np.save(fout_data_paths, data_paths)

