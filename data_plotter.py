import os, sys
import h5py
import numpy as np
import pandas as pd
from scipy.interpolate import InterpolatedUnivariateSpline
from scipy import optimize
import matplotlib.pyplot as plt
from scipy import integrate

from scipy.optimize import curve_fit
from scipy.stats import norm

import matplotlib.font_manager as font_manager
from tqdm.autonotebook import tqdm

tdc_bin = 5e-3  ## in ns

def extract_dataset(filename, dataset_name='waveform'):
    f = h5py.File(filename,'r')
    dataset = f[dataset_name]
    attrs_out = dict(dataset.attrs)
    ymults = [dataset.attrs['vertical{0}'.format(i+1)][0] for i in range(4)]
    yzeros = [dataset.attrs['vertical{0}'.format(i+1)][1] for i in range(4)]
    npoints = dataset.attrs['nPt']
    events = dataset.shape[1]//npoints
    chmask = dataset.attrs['chmask']  
    data_out = np.zeros(4*dataset.shape[1]).reshape((4, events, npoints))
    ich = 0
    for i in range(4):
        if chmask[i]:
            data_out[i] = (dataset[ich].reshape(events, npoints) - yzeros[i])*ymults[i]
            ich += 1
    f.close()
    return data_out, attrs_out


def calculate_voltages_raw(v_in, pedestal_length=400):
    v_pedestal = np.mean(v_in[:,:pedestal_length], axis=-1)
    v_preamp_adjusted = (v_in.T - v_pedestal).T
    return v_preamp_adjusted

def calculate_voltages(v_in, gain_post=-10, pedestal_length=400):
    gain_post_inv = 1.0/gain_post
    v_preamp_adjusted = gain_post_inv * calculate_voltages_raw(v_in, pedestal_length=pedestal_length)
    return v_preamp_adjusted

def calculate_tcross(v_in, percent_thresh, dt, gain_post=-10, pedestal_length=400):
    v_preamp_pedsub = calculate_voltages(v_in, gain_post=gain_post, 
                                         pedestal_length=pedestal_length)
    time = np.arange(v_in.shape[1])*dt
    idx_max = np.argmax(v_preamp_pedsub, axis=-1)
    threshold = np.max(v_preamp_pedsub, axis=-1)*percent_thresh
    t0s = np.zeros(v_in.shape[0])
    
    for evt in range(v_in.shape[0]):
        t0 = -1.0
        if idx_max[evt] > 0:
            spline = InterpolatedUnivariateSpline(time, v_preamp_pedsub[evt])        
            start = time[np.argmin(abs(spline(time[:idx_max[evt]])-threshold[evt]))]
            t0 = optimize.newton(lambda x: spline(x)-threshold[evt], x0=start, maxiter=500)
        t0s[evt] = t0
    
    return t0s

def gaus(x,a,x0,sigma):
    return a*np.exp(-(x-x0)**2/(2*sigma**2))

def plot_tcross(ich, t0s, trigger_t0s=None, ax=None, dofit=False, num_bins=20):
    mask = t0s > -0.5
    if trigger_t0s is not None:
        mask = (t0s > -0.5) & (trigger_t0s > -0.5)
    clean_t0s = t0s[mask]
    if trigger_t0s is not None:
        clean_trigger_t0s = trigger_t0s[mask]

    to_plot = clean_t0s    
    if trigger_t0s is not None:
        to_plot = clean_t0s - clean_trigger_t0s
    
    mean = np.mean(to_plot)
    sigma = np.std(to_plot, ddof=1)
    
    range_hist = (np.min(to_plot),np.max(to_plot))
    if ax is None:
        fig, ax = plt.subplots(dpi=400)
    
    if dofit:
        bins, edges = np.histogram(to_plot, num_bins, density=False)
        centers = 0.5*(edges[1:] + edges[:-1])
        try:
            popt, pcov = curve_fit(gaus,centers,bins,p0=[1,mean,sigma])
            ax.plot(centers, gaus(centers,popt[0], popt[1], popt[2]))
            mean = popt[1]
            sigma = popt[2]
        except:
            pass        
    
    ax.hist(to_plot, num_bins, range=range_hist, 
            density=False,
            label='mean = %.3g s\nsigma = %.3g\n#event = %d\n#bin = %d'%(mean,sigma,to_plot.size,num_bins))
    ax.legend()
    ax.grid(which='both')
    if trigger_t0s is None:
        ax.set(xlabel='Time (s)', ylabel='Occurance',
               title='Channel {0}'.format(ich+1))
    else:
        ax.set(xlabel=r'Time_{Trigger} - Time_{Channel} (s)', ylabel='Occurance',
               title='Channel {0}'.format(ich+1))
    
    
def calculate_charge(v_in, dt, transCond, gain_post=-10, pedestal_length=400, charge_norm=1e15):
    v_preamp_pedsub = calculate_voltages(v_in, gain_post=gain_post, 
                                         pedestal_length=pedestal_length)
    time = np.arange(v_in.shape[1])*dt
    norm = charge_norm/transCond
    return integrate.simps(norm*v_preamp_pedsub, time, axis=-1)


def plot_charge(dataset, ich, dt, transCond, mask=None, ax=None, gain_post=-10, 
                pedestal_length=400, charge_norm=1e15, num_bins=200):
    charges = calculate_charge(dataset[ich], dt, transCond, 
                               gain_post=gain_post,
                               pedestal_length=pedestal_length,                               
                               charge_norm=charge_norm)
    Q_avg = np.mean(charges)
    minmax = (np.min(charges),np.max(charges))
    range_hist = (0,10)#(minmax[0]*(0.5 if minmax[0] > 0 else 2.0),minmax[1]*(2.0 if minmax[1] > 0 else 0.5))
    if ax is None:
        fig, ax = plt.subplots(dpi=400)
    #ax.set_yscale('log')
    ax.hist(charges, num_bins, range=range_hist, 
             density=False,
             label='peak = %.2f fC\n#event = %d\n#bin = %d'%(Q_avg,dataset.shape[1],num_bins))
    ax.legend()
    ax.grid(which='both')
    ax.set(xlabel='Charge (fC)', ylabel='Occurance',
           title='Channel {0}'.format(ich+1))
    return ax


def plot_amplitude(dataset, ich, ax=None, gain_post=-10, 
                   pedestal_length=400, num_bins = 100):
    v_preamp_pedsub = calculate_voltages(dataset[ich], gain_post=gain_post, 
                                         pedestal_length=pedestal_length)
    v_pk = np.max(v_preamp_pedsub, axis=-1)
    
    range_ampl = (0, 0.3)#(np.min(v_pk)*0.5,np.max(v_pk)*2)
    if ax is None:
        fig, ax = plt.subplots(dpi=400)
    ax.hist(v_pk, num_bins, range=range_ampl, density=False,
            label='#event = %d\n#bin = %d'%(dataset.shape[1],num_bins))
    ax.legend()
    ax.grid()
    ax.set(xlabel='Amplitude (V)', ylabel='Occurance',
           title='Channel {0}'.format(ich+1))
    return ax

def plot_waveform(time, voltage, pp, xlable="Time(ns)", ylable="Voltage(V)", title="Raw Data ch1", pdf=False, pic=False):
    fig, ax1 = plt.subplots(dpi=200)
    for ab in tqdm(range(0,len(voltage))):
        ax1.plot(time, voltage[ab])
    # ax1.set_xlim(left=0,right=30)
    # ax1.set_ylim(bottom=0.20,top=0.50)
    ax1.grid()
    ax1.set(xlabel='Time(ns)', ylabel='Voltage(V)',
           title='Raw Data ch1')
    if pdf:
        pp.savefig(fig)
        pp.close()
    if pic:
        plt.show()
    plt.close(fig)

def plot_waveforms(time, v_ch1, v_ch2, v_ch3, v_ch4, pp, xlable="Time(ns)", ylable="Voltage(V)", 
                   title="Raw Data ch1", pdf=False, pic=False):
    fig, ax1 = plt.subplots(dpi=200)
    for ab in tqdm(range(0,len(v_ch1))):
        ax1.plot(time, v_ch1[ab])
    # ax1.set_xlim(left=0,right=30)
    # ax1.set_ylim(bottom=0.20,top=0.50)
    ax1.grid()
    ax1.set(xlabel='Time(ns)', ylabel='Voltage(V)',
           title='Raw Data ch1')
    if pdf==True:
        pp.savefig(fig)
    if pic==True:
        plt.show()
    plt.close(fig)
    
    fig, ax2 = plt.subplots(dpi=200)
    for ab in tqdm(range(0,len(v_ch2))):
        ax2.plot(x*dt*1e9, v_ch2[ab])
    # ax1.set_xlim(left=0,right=30)
    # ax1.set_ylim(bottom=0.20,top=0.50)
    ax2.grid()
    ax2.set(xlabel='Time(ns)', ylabel='Voltage(V)',
           title='Raw Data ch2')
    if pdf:
        pp.savefig(fig)
    if pic:
        plt.show()
    plt.close(fig)
    
    fig, ax3 = plt.subplots(dpi=200)
    for ab in tqdm(range(0,len(v_ch3))):
        ax3.plot(x*dt*1e9, v_ch3[ab])
    # ax1.set_xlim(left=0,right=30)
    # ax1.set_ylim(bottom=0.20,top=0.50)
    ax3.grid()
    ax3.set(xlabel='Time(ns)', ylabel='Voltage(V)',
           title='Raw Data ch3')
    if pdf:
        pp.savefig(fig)
    if pic:
        plt.show()
    plt.close(fig)
    
    fig, ax4 = plt.subplots(dpi=200)
    for ab in tqdm(range(0,len(v_ch4))):
        ax4.plot(x*dt*1e9, v_ch4[ab])
    # ax1.set_xlim(left=0,right=30)
    # ax1.set_ylim(bottom=0.20,top=0.50)
    ax4.grid()
    ax4.set(xlabel='Time(ns)', ylabel='Voltage(V)',
           title='Raw Data ch4')
    if pdf:
        pp.savefig(fig)
    if pic:
        plt.show()
    plt.close(fig)


##### signal processing for all channels #############
def plotting_job(afile, scope_config, outfile):
    from matplotlib.backends.backend_pdf import PdfPages
    tc = scope_config['transcond']['lowgain']
    data, attrs = extract_dataset(afile)    
    pp = PdfPages(outfile)
    trigger_t0s = None
    measure_t0s = {}
    ch1 = np.max(calculate_voltages(data[0], gain_post=scope_config['gains'][0]), axis=-1) > 0.015
    ch2 = np.max(calculate_voltages(data[1], gain_post=scope_config['gains'][1]), axis=-1) > 0.015
    ch3 = np.max(calculate_voltages(data[2], gain_post=scope_config['gains'][2]), axis=-1) > 0.015
    mask = (ch1 & ch2 & ch3)
    for ch in range(4):        
        if attrs['chmask'][ch]:            
            fig, ax = plt.subplots(dpi=400)
            thegain = scope_config['gains'][ch]
            plot_amplitude(data[:,mask,:], ch, ax=ax, gain_post=thegain)
            pp.savefig(fig)
            plt.close(fig)

            fig, ax = plt.subplots(dpi=400)
            plot_charge(data[:,mask,:], ch, attrs['dt'], tc, ax=ax, gain_post=thegain)                       
            pp.savefig(fig)
            plt.close(fig)
            t0s = calculate_tcross(data[ch], scope_config['thresholds'][ch], 
                                    attrs['dt'], gain_post=thegain)
            fig, ax = plt.subplots(dpi=400)
            plot_tcross(ch, t0s, ax=ax)            
            pp.savefig(fig)
            plt.close(fig)
            if ch == scope_config['trigger']:
                trigger_t0s = t0s
            else:
                measure_t0s[ch] = t0s
            
    #fig, ax = plt.subplots(1, len(measure_t0s.keys()), dpi=400)
    nch = len(measure_t0s.keys())
    iax = 0
    for ch, t0s in measure_t0s.items():
        fig, ax = plt.subplots(1, 1, dpi=400)
        plot_tcross(ch, t0s, trigger_t0s=trigger_t0s, ax=ax)
        pp.savefig(fig)
        plt.close(fig)
        iax += 1
    pp.close()

gain_post = -1.0
scope_config = {'trigger': 2,
                'transcond':{'highgain': 15.7e3, 'lowgain': 4.4e3},
                'gains': [gain_post, gain_post, gain_post, 1.0],
                'thresholds': [0.2, 0.2, 0.2, 0.5]}

import sys
import glob
import time

data_path = sys.argv[1]
print(data_path.split('/'))
out_path = '/'.join(data_path.split('/')[:-1])
print('out path ->', out_path)
if len(sys.argv) > 2:
    out_path = sys.argv[2]
processed_files = set()

while True:
    files = set(glob.glob(os.path.join(data_path,'*.hdf5')))
    files_to_process = files - processed_files
    if len(files_to_process):
        for afile in tqdm(files_to_process):            
            outfile = afile[:afile.rfind('.')].split('/')[-1] + '.pdf'
            fname = os.path.join(out_path, outfile)
            plotting_job(afile, scope_config, fname)
            processed_files.add(afile)
    else:
        time.sleep(1)