#!/usr/bin/env python
# -*- coding: utf-8 -*-

import pyfits
import glob
import numpy as np
import bayesflare as pf
import scipy.signal as signal
import matplotlib.mlab as ml
import matplotlib.pyplot as pl
import copy

__all__ = ["Loader", "Lightcurve"]

class Loader():
    """ An interface for finding Kepler data stored locally given a specific directory structure.

    Parameters
    ----------
    data_root -- string
       A string containing the path to a folder containing the data from the Kepler mission.
       This data should be stored in the following format:
       ::
          | data_root/
          |          |/Q1_public
          |          |/Q2_public
          |          .
          |          .

       This parameter is optional, and can also be loaded from the ``KPLR_ROOT`` environment
       variable.
    """

    def __init__(self, data_root=None):
        self.data_root = data_root
        if data_root is None:
            self.data_root = KPLR_ROOT

    def __str__(self):
        return "<BayesFlare Data Loader (data_root=\"{0}\")>".format(self.data_root)

    def __unicode__(self):
        return self.__str__()

    def __repr__(self):
        return self.__str__()

    def find(self, kic, short=False, quarters="1-9"):
        """ Finds all local files which correspond to a given star,
        from all available data collection quarters, either from
        short or long cadence data.

        Parameters
        ----------
        kic : int, str
           The Kepler Input Catalogue ID for the star
        short : bool, optional
           A boolean flag which determines whether or not short cadence light curves should be returned.
           Defaults to False.
        quarters : str, optional
           A quarter, or a range of quarters in the format "first-last", for example

              >>> Loader.find(757450, quarters="2-3")

           will retrieve all quarter 2 and 3 data for the star KIC757450.
           By default, retrieves all quarters between 1 and 9.

        Returns
        -------
        list
           A list containing the paths to every qualifying lightcurve.

        Examples
        --------

        >>> Loader.find(757450, short=True, quarters="1")

        Will return the short cadence light curves for KIC757450 in quarter 1.
        """
        kic = str('%09d'%int(kic))
        if short==False:
            return sorted(glob.glob(self.data_root+'/Q['+quarters+']_public/kplr'+kic+'*_llc.fits'))
        else:
            return sorted(glob.glob(self.data_root+'/Q['+quarters+']_public/kplr'+kic+'*.fits'))


class Lightcurve():
    """
    A class designed to handle the day-to-day requirements for
    Kepler light curves, including removing DC offsets.

    Parameters
    ----------
    curve : string
       The file name for a light curves.
    """

    id = 0   # The KIC number of the star

    clc = np.array([])
    cts = np.array([])
    cle = np.array([])

    ulc = np.array([])    # Place to store the unsmoothed curve.

    dc  = 0 # Stored DC offset.

    filterfit = np.array([])

    quarter = ""

    detrended = False
    detrend_nbins = 0
    detrend_order = 0
    detrend_fit = np.array([])

    running_median_dt = 0
    running_median_fit = np.array([])
    datagap = False

    def __init__(self, curve=None, detrend=False, nbins=101, order=3, maxgap=1):

        clc = None
        clc = np.array([])
        if curve != None:
            self.add_data(curve, detrend, nbins, order, maxgap=1)

    def __str__(self):
        return "<bayesflare Lightcurve for KIC "+str(self.id)+">"

    def __unicode__(self):
        return self.__str__()

    def __repr__(self):
        return self.__str__()

    def identity_string(self):
        """
        Returns a string which identifies the lightcurve.

        Returns
        -------
        str
           An identifier of the light curve based on its length and cadence.
        """
        return "lc_len_"+str(len(self.clc))+"_cad_"+str(self.cadence)

    def dt(self):
        """
        Calculate the sample separation for the light curve.

        Returns
        -------
        float
           The separation time for data in the light curve.
        """
        return self.cts[1] - self.cts[0]

    def fs(self):
        """
        Calculate the sample frequency of the light curve.

        Returns
        -------
        float
           The sample frequency of the light curve.
        """
        return 1.0 / self.dt()

    def psd(self):
        """
        Calculate the one-sided non-windowed power spectrum of the light curve. This uses the
        :func:`matplotlib.mlab.psd` function for computing the power spectrum, with a single
        non-overlapping FFT.

        Returns
        -------
        sk : array-like
           The Power spectral density of the light curve.
        f  : array-like
           An array of the frequencies.
        """
        l = len(self.clc)

        # get the power spectrum of the lightcurve data
        sk, f = ml.psd(x=self.clc, window=signal.boxcar(l), noverlap=0, NFFT=l, Fs=self.fs(), sides='onesided')

        # return power spectral density and array of frequencies
        return sk, f

    def add_data(self, curve=None, detrend=False, nbins=101, order=3, maxgap=1):
        """
        Add light curve data to the object..

        Parameters
        ----------
        curvefile : string
           The file path file pointing to a light curve fits files.
        detrend : bool, optional, default: False
           A boolean flag which determines whether light curve should be detrended using the
           Savitsky-Golay filter (:func:`.savitzky_golay`).
        nbins : int, optional, default: 101
           The width of the detrending window in bins of the light curve.
        order : int, optional, default: 3
           The polynomial order of the detrending filter.
        maxgap : int, optional, default+1
           The largest gap size (in bins) allowed before the light curve is deemed to contain gaps.

        Exceptions
        ----------
        NameError
           This needs to be replaced with an exception specific to the package!
           Error is raised if there is an I/O error while accessing a light curve file.
        """
        if curve == None:
            raise NameError("[Error] No light curve file given")

        try:
            dcurve = pyfits.open(curve)
        except IOError:
            raise NameError("[Error] An IO error occured when trying to access "+curve )
            mis_file = open('ioerror-files.log', 'a')
            mis_file.write(curve+'\n')
            mis_file.close()
            return

        if len(self.clc) == 0:
            self.id = dcurve[0].header['KEPLERID']
        elif dcurve[0].header['KEPLERID'] != self.id:
            raise NameError("Tried to add data from KIC"+str(dcurve[0].header['KEPLERID'])+" to KIC"+str(self.id))

        if dcurve[0].header['OBSMODE'] == 'long cadence':
            self.cadence = 'long'
        else:
            self.cadence = 'short'

        self.quarter = str(self.quarter)+str(dcurve[0].header['QUARTER'])

        # Assemble the new data into the class
        self.clc = np.append(self.clc, copy.deepcopy(dcurve[1].data['PDCSAP_FLUX']))
        self.cts = np.append(self.cts, copy.deepcopy(dcurve[1].data['TIME']*24*3600))
        self.cle = np.append(self.cle, copy.deepcopy(dcurve[1].data['PDCSAP_FLUX_ERR']))

        dcurve.close()
        self.datagap = self.gap_checker(self.clc, maxgap=maxgap)
        self.interpolate()
        self.dcoffset() # remove a DC offset (calculated as the median of the light curve)

        if detrend:
            self.detrend(nbins, order)

        del dcurve

    def dcoffset(self):
        """
        Method to remove a DC offset from a light curve by subtracting the median value of the
        light curve from all values.
        """
        self.dc  = np.median(self.clc)
        self.clc = self.clc - self.dc

    def gap_checker(self, d, maxgap=1):
        """
        Check for NaN gaps in the data greater than a given value.

        Parameters
        ----------
        d : :class:`numpy.ndarray`
           The array to check for gaps in the data.

        maxgap : int, optional, default: 1
           The maximum allowed size of gaps in the data.

        Returns
        -------
        bool
           ``True`` if there is a gap of maxgap or greater exists in ``d``, otherwise ``False``.
        """

        z = np.invert(np.isnan(d))
        y = np.diff(z.nonzero()[0])
        if len(y < maxgap+1) != len(y):
          return True
        else:
          return False

    def nan_helper(self, y):
        """
        Helper to handle indices and logical indices of NaNs.

        Parameters
        ----------
        y : ndarray
           An array which may contain NaN values.

        Returns
        -------
        nans : ndarray
          An array containing the indices of NaNs
        index : function
          A function, to convert logical indices of NaNs to 'equivalent' indices

        Examples
        --------

           >>> # linear interpolation of NaNs
           >>> spam = np.ones(100)
           >>> spam[10] = np.nan
           >>> camelot = pf.Lightcurve(curves)
           >>> nans, x = camelot.nan_helper(spam)
           >>> spam[nans]= np.interp(x(nans), x(~nans), spam[~nans])


        """

        return np.isnan(y), lambda z: z.nonzero()[0]

    def interpolate(self):
        """
        A method for interpolating the light curves, to compensate for NaN values.

        Examples
        --------

           >>> camelot = pf.Lightcurve(curves)
           >>> camelot.interpolate()

        """

        #for a in np.arange(len(self.lc)):
        z = self.clc
        nans, za= self.nan_helper(z)
        z[nans]= np.interp(za(nans), za(~nans), z[~nans]).astype('float32')
        self.clc = z

    def set_detrend(nbins, order):
        """
        A method allowing the detrending parameters for the light curve to be changed.

        Parameters
        ----------
        nbins : int
           The length of the detrending window, in bins.

        order : int
           The order of the detrending filter.

        See also
        --------
        detrend

        """
        self.detrend_length=nbins
        self.detrend_order

    def detrend(self, nbins, order):
        """
        A method to detrend the light curve using a Savitsky-Golay filter (:func:`.savitzky_golay`).

        Parameters
        ----------
        nbins : int
           The number of bins in the running detrend window
        order : int
           The polynomial order of the detrending fit.

        """
        self.detrend_nbins = nbins
        self.detrend_order = order
        self.detrended = True

        self.ulc = self.clc
        ffit = pf.savitzky_golay(self.clc, nbins, order)
        self.clc = (self.clc - ffit)
        self.detrend_fit = np.copy(ffit)

    def running_median(self, dt):
        """
        A method to subtract a running median for smoothing the light curve (for example as an
        alternative to the Savitsky-Golay detrending).

        Parameters
        ----------
        dt : float
           the time window (in seconds) for the running median
        """
        ffit = np.array([])

        self.running_median_dt = dt

        for i in range(len(self.clc)):
            v = (self.cts < (self.cts[i]+dt/2.)) & (self.cts > (self.cts[i]-dt/2.))
            ffit = np.append(ffit, np.median(self.clc[v]))

        self.running_median_fit = np.copy(ffit)
        self.ulc = self.clc
        self.clc = (self.clc - ffit)

    def plot(self, figsize=(10,3)):
        """
        Method to produce a plot of the light curve.

        Parameters
        ----------
        figsize : tuple
           The size of the output plot.

        """
        fig, ax = pl.subplots(1)
        pl.title('Lightcurve for KIC'+str(self.id))
        self.trace = ax.plot(self.cts/(24*3600.0), self.clc)
        fig.autofmt_xdate()
        pl.xlabel('Time [days]')
        pl.ylabel('Luminosity')
        pl.show()

