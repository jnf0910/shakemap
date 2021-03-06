#!/usr/bin/env python

# stdlib imports

# third party imports
from mapio.gmt import GMTGrid
from mapio.gdal import GDALGrid
from mapio.grid2d import Grid2D
from mapio.geodict import GeoDict
from openquake.hazardlib.gsim.base import SitesContext
import numpy as np

# local imports
from shakemap.utils.exception import ShakeMapException


def _load(vs30File, samplegeodict=None, resample=False, method='linear',
          doPadding=False, padValue=np.nan):
    try:
        vs30grid = GMTGrid.load(vs30File, samplegeodict=samplegeodict,
                                resample=resample, method=method,
                                doPadding=doPadding, padValue=padValue)
    except Exception as msg1:
        try:
            vs30grid = GDALGrid.load(vs30File, samplegeodict=samplegeodict,
                                     resample=resample, method=method,
                                     doPadding=doPadding, padValue=padValue)
        except Exception as msg2:
            msg = 'Load failure of %s - error messages: "%s"\n "%s"' % (
                vs30File, str(msg1), str(msg2))
            raise ShakeMapException(msg)

    if vs30grid.getData().dtype != np.float64:
        vs30grid.setData(vs30grid.getData().astype(np.float64))

    return vs30grid


def _getFileGeoDict(fname):
    geodict = None
    try:
        geodict = GMTGrid.getFileGeoDict(fname)
    except Exception as msg1:
        try:
            geodict = GDALGrid.getFileGeoDict(fname)
        except Exception as msg2:
            msg = 'File geodict failure with %s - error messages: "%s"\n "%s"' % (
                fname, str(msg1), str(msg2))
            raise ShakeMapException(msg)
    return geodict


def _calculate_z1p0(vs30):
    # I think these are older generation equations (c2008). Probably need to be
    # more careful about what version of these equations are used.
    c1 = 6.745
    c2 = 1.35
    c3 = 5.394
    c4 = 4.48
    Z1Pt0 = np.zeros_like(vs30)
    Z1Pt0[vs30 < 180] = np.exp(c1)
    idx = (vs30 >= 180) & (vs30 <= 500)
    Z1Pt0[idx] = np.exp(c1 - c2 * np.log(vs30[idx] / 180.0))
    idx = vs30 > 500
    Z1Pt0[idx] = np.exp(c3 - c4 * np.log(vs30[idx] / 500.0))
    return Z1Pt0


def _calculate_z2p5(z1pt0):
    # I think these are older generation equations (c2008). Probably need to be
    # more careful about what version of these equations are used.
    c1 = 519
    c2 = 3.595
    Z2Pt5 = c1 + z1pt0 * c2
    return Z2Pt5


class Sites(object):
    """
    An object to encapsulate information used to generate a GEM 
    `SitesContext <https://github.com/gem/oq-hazardlib/blob/master/openquake/hazardlib/gsim/base.py>`__.
    """

    def __init__(self, vs30grid, vs30measured_grid=None, backarc=False,
                 defaultVs30=686.0):
        """
        Construct a Sites object.

        :param vs30grid:
            MapIO Grid2D object containing Vs30 values.
        :param vs30measured_grid:
            Boolean grid indicating whether Vs30 values were measured or derived
            (i.e., from slope)
        :param backarc:
            Boolean indicating whether event is on the backarc as defined 
            `here <http://earthquake.usgs.gov/learn/glossary/?term=backarc>`__.
        :param defaultVs30:
          Default Vs30 value to use in locations where Vs30Grid is not specified.
        """
        self._Vs30 = vs30grid
        self._backarc = backarc
        self._defaultVs30 = defaultVs30
        self._vs30measured_grid = vs30measured_grid
        self._GeoDict = vs30grid.getGeoDict().copy()
        self._lons = np.linspace(self._GeoDict.xmin,
                                 self._GeoDict.xmax,
                                 self._GeoDict.nx)
        self._lats = np.linspace(self._GeoDict.ymin,
                                 self._GeoDict.ymax,
                                 self._GeoDict.ny)
        self._Z1Pt0 = _calculate_z1p0(self._Vs30.getData())
        self._Z2Pt5 = _calculate_z2p5(self._Z1Pt0)

    @classmethod
    def _create(cls, geodict, defaultVs30, vs30File, padding, resample):
        if vs30File is not None:
            fgeodict = _getFileGeoDict(vs30File)
            if not resample:
                if not padding:
                    # we want something that is within and aligned
                    geodict = fgeodict.getBoundsWithin(geodict)
                else:
                    # we want something that is just aligned, since we're
                    # padding edges
                    geodict = fgeodict.getAligned(geodict)
            vs30grid = _load(vs30File, samplegeodict=geodict,
                             resample=resample, method='linear',
                             doPadding=padding, padValue=defaultVs30)

        return vs30grid

    @classmethod
    def createFromBounds(cls, xmin, xmax, ymin, ymax, dx, dy, defaultVs30=686.0,
                         vs30File=None, vs30measured_grid=None,
                         backarc=False, padding=False, resample=False):
        """
        Create a Sites object by defining a center point, resolution, extent, 
        and Vs30 values.

        :param xmin:
            X coordinate of left edge of bounds.
        :param xmax:
            X coordinate of right edge of bounds.
        :param ymin:
            Y coordinate of bottom edge of bounds.
        :param ymax:
            Y coordinate of top edge of bounds.
        :param dx:
            Resolution of desired grid in X direction.
        :param dy:
            Resolution of desired grid in Y direction.
        :param defaultVs30:
            Default Vs30 value to use if vs30File not specified.
        :param vs30File:
            Name of GMT or GDAL format grid file containing Vs30 values.
        :param vs30measured_grid:
            Boolean grid indicating whether Vs30 values were measured or derived 
            (i.e., from slope)
        :param backarc:
            Boolean indicating whether event is on the backarc as defined
            `here <http://earthquake.usgs.gov/learn/glossary/?term=backarc>`__.
        :param padding:
            Boolean indicating whether or not to pad resulting Vs30 grid out to
            edges of input bounds. If False, grid will be clipped to the extent
            of the input file.
        :param resample:
            Boolean indicating whether or not the grid should be resampled.
        """
        geodict = GeoDict.createDictFromBox(xmin, xmax, ymin, ymax, dx, dy)
        if vs30File is not None:
            vs30grid = cls._create(geodict, defaultVs30,
                                   vs30File, padding, resample)
        else:
            griddata = np.ones((geodict.ny, geodict.nx),
                               dtype=np.float64) * defaultVs30
            vs30grid = Grid2D(griddata, geodict)
        return cls(vs30grid, vs30measured_grid=vs30measured_grid,
                   backarc=backarc, defaultVs30=defaultVs30)

    @classmethod
    def createFromCenter(cls, cx, cy, xspan, yspan, dx, dy, defaultVs30=686.0,
                         vs30File=None, vs30measured_grid=None,
                         backarc=False, padding=False, resample=False):
        """
        Create a Sites object by defining a center point, resolution, extent, 
        and Vs30 values.

        :param cx:
            X coordinate of desired center point.
        :param cy:
            Y coordinate of desired center point.
        :param xspan:
            Width of desired grid.
        :param yspan:
            Height of desired grid.
        :param dx:
            Resolution of desired grid in X direction.
        :param dy:
            Resolution of desired grid in Y direction.
        :param defaultVs30:
            Default Vs30 value to use if vs30File not specified.
        :param vs30File:
            Name of GMT or GDAL format grid file containing Vs30 values.
        :param vs30measured_grid:
            Boolean grid indicating whether Vs30 values were measured or derived 
            (i.e., from slope)
        :param backarc:
            Boolean indicating whether event is on the backarc as defined
            `here <http://earthquake.usgs.gov/learn/glossary/?term=backarc>`__.
        :param padding:
            Boolean indicating whether or not to pad resulting Vs30 grid out to
            edges of input bounds. If False, grid will be clipped to the extent
            of the input file.
        :param resample:
            Boolean indicating whether or not the grid should be resampled.
        """
        geodict = GeoDict.createDictFromCenter(cx, cy, dx, dy, xspan, yspan)
        if vs30File is not None:
            vs30grid = cls._create(geodict, defaultVs30,
                                   vs30File, padding, resample)
        else:
            griddata = np.ones((geodict.ny, geodict.nx),
                               dtype=np.float64) * defaultVs30
            vs30grid = Grid2D(griddata, geodict)
        return cls(vs30grid, vs30measured_grid=vs30measured_grid,
                   backarc=backarc, defaultVs30=defaultVs30)

    def sampleFromSites(self, lats, lons, vs30measured_grid=None):
        """
        Create a SitesContext object by sampling the current Sites object.

        :param lats:
            Sequence of latitudes.
        :param lons:
            Sequence of longitudes.
        :param vs30measured_grid:
            Sequence of booleans of the same shape as lats/lons indicating 
            whether the vs30 values are measured or inferred.
        :returns:
            SitesContext object where data are sampled from the current Sites
            object.
        :raises ShakeMapException:
             When lat/lon input sequences do not share dimensionality.
        """
        lats = np.array(lats)
        lons = np.array(lons)
        latshape = lats.shape
        lonshape = lons.shape
        if latshape != lonshape:
            msg = 'Input lat/lon arrays must have the same dimensions'
            raise ShakeMapException(msg)

        site = SitesContext()
        # use default vs30 if outside grid
        site.vs30 = self._Vs30.getValue(lats, lons, default=self._defaultVs30)
        site.lats = lats
        site.lons = lons
        site.z1pt0 = _calculate_z1p0(site.vs30)
        site.z2pt5 = _calculate_z2p5(site.z1pt0)
        if vs30measured_grid is None:  # If we don't know, then use false
            site.vs30measured = np.zeros_like(lons, dtype=bool)
        else:
            site.vs30measured = vs30measured_grid
        site.backarc = self._backarc

        return site

    def getVs30Grid(self):
        """
        :returns:
            Grid2D object containing Vs30 values for this Sites object.
        """
        return self._Vs30

    def getSitesContext(self):
        """
        :returns:
           SitesContext object.
        """
        sctx = SitesContext()
        sctx.vs30 = self._Vs30.getData().copy()
        sctx.z1pt0 = self._Z1Pt0
        sctx.z2pt5 = self._Z2Pt5
        sctx.backarc = self._backarc  # zoneconfig might have this info
        if self._vs30measured_grid is None:  # If we don't know, then use false
            sctx.vs30measured = np.zeros_like(
                sctx.vs30, dtype=bool)
        else:
            sctx.vs30measured = self._vs30measured_grid
        sctx.lons = self._lons
        sctx.lats = self._lats
        return sctx
