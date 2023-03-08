# Licensed under a 3-clause BSD style license - see LICENSE.rst
"""
This module provides tools for generating radial profiles and curves of
growth.
"""

import math
import warnings

import numpy as np
from astropy.utils import lazyproperty
from astropy.utils.exceptions import AstropyUserWarning

from photutils.utils._quantity_helpers import process_quantities

__all__ = ['ProfileBase', 'CurveOfGrowth', 'RadialProfile']


class ProfileBase:
    """
    Base class for profile classes.

    Parameters
    ----------
    data : 2D `numpy.ndarray`
        The 2D data array. The data should be background-subtracted.

    xycen : tuple of 2 floats
        The ``(x, y)`` pixel coordinate of the source center.

    min_radius : float
        The minimum radius for the profile.

    max_radius : float
        The maximum radius for the profile.

    radius_step : float
        The radial step size in pixels.

    error : 2D `numpy.ndarray`, optional
        The 1-sigma errors of the input ``data``. ``error`` is assumed
        to include all sources of error, including the Poisson error
        of the sources (see `~photutils.utils.calc_total_error`) .
        ``error`` must have the same shape as the input ``data``.

    mask : 2D bool `numpy.ndarray`, optional
        A boolean mask with the same shape as ``data`` where a `True`
        value indicates the corresponding element of ``data`` is masked.
        Masked data are excluded from all calculations.

    method : {'exact', 'center', 'subpixel'}, optional
        The method used to determine the overlap of the aperture on the
        pixel grid:

            * ``'exact'`` (default):
              The the exact fractional overlap of the aperture and each
              pixel is calculated. The aperture weights will contain
              values between 0 and 1.

            * ``'center'``:
              A pixel is considered to be entirely in or out of the
              aperture depending on whether its center is in or out of
              the aperture. The aperture weights will contain values
              only of 0 (out) and 1 (in).

            * ``'subpixel'``:
              A pixel is divided into subpixels (see the ``subpixels``
              keyword), each of which are considered to be entirely in
              or out of the aperture depending on whether its center is
              in or out of the aperture. If ``subpixels=1``, this method
              is equivalent to ``'center'``. The aperture weights will
              contain values between 0 and 1.

    subpixels : int, optional
        For the ``'subpixel'`` method, resample pixels by this factor
        in each dimension. That is, each pixel is divided into
        ``subpixels**2`` subpixels. This keyword is ignored unless
        ``method='subpixel'``.
    """

    _circular_radii = None
    profile = None
    profile_error = None

    def __init__(self, data, xycen, min_radius, max_radius, radius_step, *,
                 error=None, mask=None, method='exact', subpixels=5):

        (data, error), unit = process_quantities((data, error),
                                                 ('data', 'error'))
        self.data = data
        self.unit = unit
        self.xycen = xycen

        if min_radius < 0 or max_radius < 0:
            raise ValueError('min_radius and max_radius must be >= 0')
        if min_radius >= max_radius:
            raise ValueError('max_radius must be greater than min_radius')
        if radius_step <= 0:
            raise ValueError('radius_step must be > 0')
        self.min_radius = min_radius
        self.max_radius = max_radius
        self.radius_step = radius_step

        if error is not None and error.shape != data.shape:
            raise ValueError('error must have the same same as data')
        self.error = error
        if mask is not None and mask.shape != data.shape:
            raise ValueError('mask must have the same same as data')
        self.mask = mask

        self.method = method
        self.subpixels = subpixels

    @lazyproperty
    def radius(self):
        """
        The profile radius in pixels as a 1D `~numpy.ndarray`.
        """
        nsteps = int(math.floor((self.max_radius - self.min_radius)
                                / self.radius_step))
        max_radius = self.min_radius + (nsteps * self.radius_step)
        return np.linspace(self.min_radius, max_radius, nsteps + 1)

    @lazyproperty
    def _circular_apertures(self):
        """
        A list of `~photutils.aperture.CircularAperture` objects.

        The first element may be `None`.
        """
        from photutils.aperture import CircularAperture

        apertures = []
        for radius in self._circular_radii:
            if radius <= 0.0:
                aper = None
            else:
                aper = CircularAperture(self.xycen, radius)
            apertures.append(aper)
        return apertures

    @lazyproperty
    def _photometry(self):
        """
        The aperture fluxes, flux errors, and areas as a function of
        radius.
        """
        fluxes = []
        fluxerrs = []
        areas = []
        for aperture in self._circular_apertures:
            if aperture is None:
                flux, fluxerr = [0.0], [0.0]
                area = 0.0
            else:
                flux, fluxerr = aperture.do_photometry(
                    self.data, error=self.error, mask=self.mask,
                    method=self.method, subpixels=self.subpixels)
                area = aperture.area_overlap(self.data, mask=self.mask,
                                             method=self.method,
                                             subpixels=self.subpixels)
            fluxes.append(flux[0])
            if self.error is not None:
                fluxerrs.append(fluxerr[0])
            areas.append(area)

        fluxes = np.array(fluxes)
        fluxerrs = np.array(fluxerrs)
        areas = np.array(areas)
        if self.unit is not None:
            fluxes <<= self.unit
            fluxerrs <<= self.unit

        return fluxes, fluxerrs, areas

    def normalize(self, method='max'):
        """
        Normalize the profile.

        Parameters
        ----------
        method : {'max', 'sum'}, optional
            The method used to normalize the profile:

                * 'max' (default):
                  The profile is normalized such that its peak value is
                  1.
                * 'sum':
                  The profile is normalized such that its sum (integral)
                  is 1.
        """
        if method == 'max':
            normalization = self.profile.max()
        elif method == 'sum':
            normalization = self.profile.sum()
        else:
            raise ValueError('invalid method, must be "peak" or "integral"')

        if normalization == 0:
            warnings.warn('The profile cannot be normalized because the '
                          'max or sum is zero.', AstropyUserWarning)
        else:
            self.__dict__['profile'] = self.profile / normalization
            self.__dict__['profile_error'] = self.profile_error / normalization

    def plot(self, ax=None, **kwargs):
        """
        Plot the profile.

        Parameters
        ----------
        ax : `matplotlib.axes.Axes` or `None`, optional
            The matplotlib axes on which to plot.  If `None`, then the
            current `~matplotlib.axes.Axes` instance is used.

        **kwargs : `dict`
            Any keyword arguments accepted by `matplotlib.pyplot.plot`.

        Returns
        -------
        lines : list of `~matplotlib.lines.Line2D`
            A list of lines representing the plotted data.
        """
        import matplotlib.pyplot as plt

        if ax is None:
            ax = plt.gca()

        lines = ax.plot(self.radius, self.profile, **kwargs)
        ax.set_xlabel('Radius (pixels)')
        ylabel = 'Profile'
        if self.unit is not None:
            ylabel = f'{ylabel} ({self.unit})'
        ax.set_ylabel(ylabel)

        return lines

    def plot_error(self, ax=None, **kwargs):
        """
        Plot the profile errors.

        Parameters
        ----------
        ax : `matplotlib.axes.Axes` or `None`, optional
            The matplotlib axes on which to plot.  If `None`, then the
            current `~matplotlib.axes.Axes` instance is used.

        **kwargs : `dict`
            Any keyword arguments accepted by
            `matplotlib.pyplot.fill_between`.

        Returns
        -------
        lines : `matplotlib.collections.PolyCollection`
            A `~matplotlib.collections.PolyCollection` containing the
            plotted polygons.
        """
        if self.profile_error.shape == (0,):
            warnings.warn('Errors were not input', AstropyUserWarning)
            return None

        import matplotlib.pyplot as plt

        if ax is None:
            ax = plt.gca()

        # set default fill_between facecolor
        # facecolor must be first key, otherwise it will override color kwarg
        # (i.e., cannot use setdefault here)
        if 'facecolor' not in kwargs:
            kws = {'facecolor': (0.5, 0.5, 0.5, 0.3)}
            kws.update(kwargs)
        else:
            kws = kwargs

        profile = self.profile
        profile_error = self.profile_error
        if self.unit is not None:
            profile = profile.value
            profile_error = profile_error.value
        ymin = profile - profile_error
        ymax = profile + profile_error
        polycoll = ax.fill_between(self.radius, ymin, ymax, **kws)

        return polycoll


class CurveOfGrowth(ProfileBase):
    """
    Class to create a curve of growth using concentric circular
    apertures.

    The curve of growth profile represents the circular aperture flux as
    a function of circular radius.

    Parameters
    ----------
    data : 2D `numpy.ndarray`
        The 2D data array. The data should be background-subtracted.

    xycen : tuple of 2 floats
        The ``(x, y)`` pixel coordinate of the source center.

    min_radius : float
        The minimum radius for the profile.

    max_radius : float
        The maximum radius for the profile.

    radius_step : float
        The radial step size in pixels.

    error : 2D `numpy.ndarray`, optional
        The 1-sigma errors of the input ``data``. ``error`` is assumed
        to include all sources of error, including the Poisson error
        of the sources (see `~photutils.utils.calc_total_error`) .
        ``error`` must have the same shape as the input ``data``.

    mask : 2D bool `numpy.ndarray`, optional
        A boolean mask with the same shape as ``data`` where a `True`
        value indicates the corresponding element of ``data`` is masked.
        Masked data are excluded from all calculations.

    method : {'exact', 'center', 'subpixel'}, optional
        The method used to determine the overlap of the aperture on the
        pixel grid:

            * ``'exact'`` (default):
              The the exact fractional overlap of the aperture and each
              pixel is calculated. The aperture weights will contain
              values between 0 and 1.

            * ``'center'``:
              A pixel is considered to be entirely in or out of the
              aperture depending on whether its center is in or out of
              the aperture. The aperture weights will contain values
              only of 0 (out) and 1 (in).

            * ``'subpixel'``:
              A pixel is divided into subpixels (see the ``subpixels``
              keyword), each of which are considered to be entirely in
              or out of the aperture depending on whether its center is
              in or out of the aperture. If ``subpixels=1``, this method
              is equivalent to ``'center'``. The aperture weights will
              contain values between 0 and 1.

    subpixels : int, optional
        For the ``'subpixel'`` method, resample pixels by this factor
        in each dimension. That is, each pixel is divided into
        ``subpixels**2`` subpixels. This keyword is ignored unless
        ``method='subpixel'``.

    Examples
    --------
    >>> import numpy as np
    >>> from astropy.modeling.models import Gaussian2D
    >>> from astropy.visualization import simple_norm
    >>> from photutils.centroids import centroid_quadratic
    >>> from photutils.datasets import make_noise_image
    >>> from photutils.profiles import CurveOfGrowth

    Create an artificial single source. Note that this image does not
    have any background.

    >>> gmodel = Gaussian2D(42.1, 47.8, 52.4, 4.7, 4.7, 0)
    >>> yy, xx = np.mgrid[0:100, 0:100]
    >>> data = gmodel(xx, yy)
    >>> error = make_noise_image(data.shape, mean=0., stddev=2.4, seed=123)
    >>> data += error

    Create the curve of growth.

    >>> xycen = centroid_quadratic(data, xpeak=48, ypeak=52)
    >>> min_radius = 0.0
    >>> max_radius = 25.0
    >>> radius_step = 1.0
    >>> cog = CurveOfGrowth(data, xycen, min_radius, max_radius, radius_step,
    ...                     error=error, mask=None)

    >>> print(cog.radius)  # doctest: +FLOAT_CMP
    [ 0.  1.  2.  3.  4.  5.  6.  7.  8.  9. 10. 11. 12. 13. 14. 15. 16. 17.
     18. 19. 20. 21. 22. 23. 24. 25.]

    >>> print(cog.profile)  # doctest: +FLOAT_CMP
    [   0.          130.57472018  501.34744442 1066.59182074 1760.50163608
     2502.13955554 3218.50667597 3892.81448231 4455.36403436 4869.66609313
     5201.99745378 5429.02043984 5567.28370644 5659.24831854 5695.06577065
     5783.46217755 5824.01080702 5825.59003768 5818.22316662 5866.52307412
     5896.96917375 5948.92254787 5968.30540534 5931.15611704 5941.94457249
     5942.06535486]

    >>> print(cog.profile_error)  # doctest: +FLOAT_CMP
    [  0.           5.32777186   9.37111012  13.41750992  16.62928904
      21.7350922   25.39862532  30.3867526   34.11478867  39.28263973
      43.96047829  48.11931395  52.00967328  55.7471834   60.48824739
      64.81392778  68.71042311  72.71899201  76.54959872  81.33806741
      85.98568713  91.34841248  95.5173253   99.22190499 102.51980185
     106.83601366]

    Plot the curve of growth.

    .. plot::

        import matplotlib.pyplot as plt
        import numpy as np
        from astropy.modeling.models import Gaussian2D
        from astropy.visualization import simple_norm

        from photutils.centroids import centroid_quadratic
        from photutils.datasets import make_noise_image
        from photutils.profiles import CurveOfGrowth

        # create an artificial single source
        gmodel = Gaussian2D(42.1, 47.8, 52.4, 4.7, 4.7, 0)
        yy, xx = np.mgrid[0:100, 0:100]
        data = gmodel(xx, yy)
        error = make_noise_image(data.shape, mean=0., stddev=2.4, seed=123)
        data += error

        # find the source centroid
        xycen = centroid_quadratic(data, xpeak=48, ypeak=52)

        # create the curve of growth
        min_radius = 0.0
        max_radius = 25.0
        radius_step = 1.0
        cog = CurveOfGrowth(data, xycen, min_radius, max_radius, radius_step,
                            error=error, mask=None)

        # plot the curve of growth
        cog.plot()
        cog.plot_error()

    Normalize the profile and plot the normalized curve of growth.

    .. plot::

        import matplotlib.pyplot as plt
        import numpy as np
        from astropy.modeling.models import Gaussian2D
        from astropy.visualization import simple_norm

        from photutils.centroids import centroid_quadratic
        from photutils.datasets import make_noise_image
        from photutils.profiles import CurveOfGrowth

        # create an artificial single source
        gmodel = Gaussian2D(42.1, 47.8, 52.4, 4.7, 4.7, 0)
        yy, xx = np.mgrid[0:100, 0:100]
        data = gmodel(xx, yy)
        error = make_noise_image(data.shape, mean=0., stddev=2.4, seed=123)
        data += error

        # find the source centroid
        xycen = centroid_quadratic(data, xpeak=48, ypeak=52)

        # create the curve of growth
        min_radius = 0.0
        max_radius = 25.0
        radius_step = 1.0
        cog = CurveOfGrowth(data, xycen, min_radius, max_radius, radius_step,
                            error=error, mask=None)

        # plot the curve of growth
        cog.normalize()
        cog.plot()
        cog.plot_error()

    Plot a couple of the apertures on the data.

    .. plot::

        import matplotlib.pyplot as plt
        import numpy as np
        from astropy.modeling.models import Gaussian2D
        from astropy.visualization import simple_norm

        from photutils.centroids import centroid_quadratic
        from photutils.datasets import make_noise_image
        from photutils.profiles import CurveOfGrowth

        # create an artificial single source
        gmodel = Gaussian2D(42.1, 47.8, 52.4, 4.7, 4.7, 0)
        yy, xx = np.mgrid[0:100, 0:100]
        data = gmodel(xx, yy)
        error = make_noise_image(data.shape, mean=0., stddev=2.4, seed=123)
        data += error

        # find the source centroid
        xycen = centroid_quadratic(data, xpeak=48, ypeak=52)

        # create the curve of growth
        min_radius = 0.0
        max_radius = 25.0
        radius_step = 1.0
        cog = CurveOfGrowth(data, xycen, min_radius, max_radius, radius_step,
                            error=error, mask=None)

        norm = simple_norm(data, 'sqrt')
        plt.figure(figsize=(5, 5))
        plt.imshow(data, norm=norm)
        cog.apertures[5].plot(color='C0', lw=2)
        cog.apertures[10].plot(color='C1', lw=2)
    """

    @lazyproperty
    def _circular_radii(self):
        return self.radius

    @lazyproperty
    def apertures(self):
        """
        A list of `~photutils.aperture.CircularAperture` objects used to
        measure the profile.

        If ``radius_min`` is zero, then the first item will be `None`.
        """
        return self._circular_apertures

    @lazyproperty
    def profile(self):
        """
        The curve-of-growth profile as a 1D `~numpy.ndarray`.
        """
        return self._photometry[0]

    @lazyproperty
    def profile_error(self):
        """
        The curve-of-growth profile errors as a 1D `~numpy.ndarray`.
        """
        return self._photometry[1]

    @lazyproperty
    def area(self):
        """
        The unmasked area in each circular aperture as a function of
        radius as a 1D `~numpy.ndarray`.
        """
        return self._photometry[2]


class RadialProfile(ProfileBase):
    """
    Class to create a radial profile using concentric apertures.

    The radial profile represents the azimuthally-averaged flux in
    circular annuli apertures as a function of radius.

    Parameters
    ----------
    data : 2D `numpy.ndarray`
        The 2D data array. The data should be background-subtracted.

    xycen : tuple of 2 floats
        The ``(x, y)`` pixel coordinate of the source center.

    min_radius : float
        The minimum radius for the profile.

    max_radius : float
        The maximum radius for the profile.

    radius_step : float
        The radial step size in pixels.

    error : 2D `numpy.ndarray`, optional
        The 1-sigma errors of the input ``data``. ``error`` is assumed
        to include all sources of error, including the Poisson error
        of the sources (see `~photutils.utils.calc_total_error`) .
        ``error`` must have the same shape as the input ``data``.

    mask : 2D bool `numpy.ndarray`, optional
        A boolean mask with the same shape as ``data`` where a `True`
        value indicates the corresponding element of ``data`` is masked.
        Masked data are excluded from all calculations.

    method : {'exact', 'center', 'subpixel'}, optional
        The method used to determine the overlap of the aperture on the
        pixel grid:

            * ``'exact'`` (default):
              The the exact fractional overlap of the aperture and each
              pixel is calculated. The aperture weights will contain
              values between 0 and 1.

            * ``'center'``:
              A pixel is considered to be entirely in or out of the
              aperture depending on whether its center is in or out of
              the aperture. The aperture weights will contain values
              only of 0 (out) and 1 (in).

            * ``'subpixel'``:
              A pixel is divided into subpixels (see the ``subpixels``
              keyword), each of which are considered to be entirely in
              or out of the aperture depending on whether its center is
              in or out of the aperture. If ``subpixels=1``, this method
              is equivalent to ``'center'``. The aperture weights will
              contain values between 0 and 1.

    subpixels : int, optional
        For the ``'subpixel'`` method, resample pixels by this factor
        in each dimension. That is, each pixel is divided into
        ``subpixels**2`` subpixels. This keyword is ignored unless
        ``method='subpixel'``.

    Notes
    -----
    If the ``min_radius`` is less than or equal to half the
    ``radius_step``, then a circular aperture with radius equal to
    ``min_radius + 0.5 * radius_step`` will be used for the innermost
    aperture.

    Examples
    --------
    >>> import numpy as np
    >>> from astropy.modeling.models import Gaussian2D
    >>> from astropy.visualization import simple_norm
    >>> from photutils.centroids import centroid_quadratic
    >>> from photutils.datasets import make_noise_image
    >>> from photutils.profiles import RadialProfile

    Create an artificial single source. Note that this image does not
    have any background.

    >>> gmodel = Gaussian2D(42.1, 47.8, 52.4, 4.7, 4.7, 0)
    >>> yy, xx = np.mgrid[0:100, 0:100]
    >>> data = gmodel(xx, yy)
    >>> error = make_noise_image(data.shape, mean=0., stddev=2.4, seed=123)
    >>> data += error

    Create the radial profile.

    >>> xycen = centroid_quadratic(data, xpeak=48, ypeak=52)
    >>> min_radius = 0.0
    >>> max_radius = 25.0
    >>> radius_step = 1.0
    >>> rp = RadialProfile(data, xycen, min_radius, max_radius, radius_step,
    ...                    error=error, mask=None)

    >>> print(rp.radius)  # doctest: +FLOAT_CMP
    [ 0.  1.  2.  3.  4.  5.  6.  7.  8.  9. 10. 11. 12. 13. 14. 15. 16. 17.
     18. 19. 20. 21. 22. 23. 24. 25.]

    >>> print(rp.profile)  # doctest: +FLOAT_CMP
    [ 4.27430150e+01  4.02150658e+01  3.81601146e+01  3.38116846e+01
      2.89343205e+01  2.34250297e+01  1.84368533e+01  1.44310461e+01
      9.55543388e+00  6.55415896e+00  4.49693014e+00  2.56010523e+00
      1.50362911e+00  7.35389056e-01  6.04663625e-01  8.08820954e-01
      2.31751912e-01 -1.39063329e-01  1.25181410e-01  4.84601845e-01
      1.94567871e-01  4.49109676e-01 -2.00995374e-01 -7.74387397e-02
      5.70302749e-02 -3.27578439e-02]

    >>> print(rp.profile_error)  # doctest: +FLOAT_CMP
    [2.95008692 1.17855895 0.6610777  0.51902503 0.47524302 0.43072819
     0.39770113 0.37667594 0.33909996 0.35356048 0.30377721 0.29455808
     0.25670656 0.26599511 0.27354232 0.2430305  0.22910334 0.22204777
     0.22327174 0.23816561 0.2343794  0.2232632  0.19893783 0.17888776
     0.18228289 0.19680823]

    Plot the radial profile.

    .. plot::

        import matplotlib.pyplot as plt
        import numpy as np
        from astropy.modeling.models import Gaussian2D
        from astropy.visualization import simple_norm

        from photutils.centroids import centroid_quadratic
        from photutils.datasets import make_noise_image
        from photutils.profiles import RadialProfile

        # create an artificial single source
        gmodel = Gaussian2D(42.1, 47.8, 52.4, 4.7, 4.7, 0)
        yy, xx = np.mgrid[0:100, 0:100]
        data = gmodel(xx, yy)
        error = make_noise_image(data.shape, mean=0., stddev=2.4, seed=123)
        data += error

        # find the source centroid
        xycen = centroid_quadratic(data, xpeak=48, ypeak=52)

        # create the radial profile
        min_radius = 0.0
        max_radius = 25.0
        radius_step = 1.0
        rp = RadialProfile(data, xycen, min_radius, max_radius, radius_step,
                           error=error, mask=None)

        # plot the radial profile
        rp.plot()
        rp.plot_error()

    Normalize the profile and plot the normalized radial profile.

    .. plot::

        import matplotlib.pyplot as plt
        import numpy as np
        from astropy.modeling.models import Gaussian2D
        from astropy.visualization import simple_norm

        from photutils.centroids import centroid_quadratic
        from photutils.datasets import make_noise_image
        from photutils.profiles import RadialProfile

        # create an artificial single source
        gmodel = Gaussian2D(42.1, 47.8, 52.4, 4.7, 4.7, 0)
        yy, xx = np.mgrid[0:100, 0:100]
        data = gmodel(xx, yy)
        error = make_noise_image(data.shape, mean=0., stddev=2.4, seed=123)
        data += error

        # find the source centroid
        xycen = centroid_quadratic(data, xpeak=48, ypeak=52)

        # create the radial profile
        min_radius = 0.0
        max_radius = 25.0
        radius_step = 1.0
        rp = RadialProfile(data, xycen, min_radius, max_radius, radius_step,
                           error=error, mask=None)

        # plot the radial profile
        rp.normalize()
        rp.plot()
        rp.plot_error()

    Plot a couple of the apertures on the data.

    .. plot::

        import matplotlib.pyplot as plt
        import numpy as np
        from astropy.modeling.models import Gaussian2D
        from astropy.visualization import simple_norm

        from photutils.centroids import centroid_quadratic
        from photutils.datasets import make_noise_image
        from photutils.profiles import RadialProfile

        # create an artificial single source
        gmodel = Gaussian2D(42.1, 47.8, 52.4, 4.7, 4.7, 0)
        yy, xx = np.mgrid[0:100, 0:100]
        data = gmodel(xx, yy)
        error = make_noise_image(data.shape, mean=0., stddev=2.4, seed=123)
        data += error

        # find the source centroid
        xycen = centroid_quadratic(data, xpeak=48, ypeak=52)

        # create the radial profile
        min_radius = 0.0
        max_radius = 25.0
        radius_step = 1.0
        rp = RadialProfile(data, xycen, min_radius, max_radius, radius_step,
                           error=error, mask=None)

        norm = simple_norm(data, 'sqrt')
        plt.figure(figsize=(5, 5))
        plt.imshow(data, norm=norm)
        rp.apertures[5].plot(color='C0', lw=2)
        rp.apertures[10].plot(color='C1', lw=2)
    """

    @lazyproperty
    def _circular_radii(self):
        """
        The circular aperture radii for the radial bin edges (inner and
        outer annulus radii).
        """
        shift = self.radius_step / 2
        min_radius = self.min_radius - shift
        max_radius = self.max_radius + shift
        nsteps = int(math.floor((max_radius - min_radius)
                                / self.radius_step))
        max_radius = min_radius + (nsteps * self.radius_step)
        return np.linspace(min_radius, max_radius, nsteps + 1)

    @lazyproperty
    def apertures(self):
        """
        A list of the circular annulus apertures used to measure the
        radial profile.

        If the ``min_radius`` is less than or equal to half the
        ``radius_step``, then a circular aperture with radius equal
        to ``min_radius + 0.5 * radius_step`` will be used for the
        innermost aperture.
        """
        from photutils.aperture import CircularAnnulus, CircularAperture

        apertures = []
        for i in range(len(self._circular_radii) - 1):
            try:
                aperture = CircularAnnulus(self.xycen, self._circular_radii[i],
                                           self._circular_radii[i + 1])
            except ValueError:  # zero radius
                aperture = CircularAperture(self.xycen,
                                            self._circular_radii[i + 1])
            apertures.append(aperture)

        return apertures

    @lazyproperty
    def _flux(self):
        """
        The flux in a circular annulus.
        """
        return np.diff(self._photometry[0])

    @lazyproperty
    def _fluxerr(self):
        """
        The flux error in a circular annulus.
        """
        return np.sqrt(np.diff(self._photometry[1] ** 2))

    @lazyproperty
    def area(self):
        """
        The unmasked area in each circular annulus (or aperture) as a
        function of radius as a 1D `~numpy.ndarray`.
        """
        return np.diff(self._photometry[2])

    @lazyproperty
    def profile(self):
        """
        The radial profile as a 1D `~numpy.ndarray`.
        """
        # ignore divide-by-zero RuntimeWarning
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', RuntimeWarning)
            return self._flux / self.area

    @lazyproperty
    def profile_error(self):
        """
        The radial profile errors as a 1D `~numpy.ndarray`.
        """
        if self.error is None:
            return self._fluxerr

        # ignore divide-by-zero RuntimeWarning
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', RuntimeWarning)
            return self._fluxerr / self.area
