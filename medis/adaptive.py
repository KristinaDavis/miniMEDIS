"""
adaptive.py

functions relating to simulating an AO system with Proper
mostly code copied from the original MEDIS from Rupert

Generally, the optical prescription will call the deformable_mirror function, which will compile all information and
run sequentially all functions related to creating the adaptive optic correction (main AO functionality, relating to
atmospheric and common-path aberrations) as well as using or not CDI probes, DM corrections or errors, etc

TODO
    Add astrogrid pattern functionality from MEDIS0

"""

import numpy as np
from skimage.restoration import unwrap_phase
from scipy import interpolate, ndimage
from inspect import getframeinfo, stack
import proper

from medis.params import sp, tp, ap, cdip
import medis.CDI as cdi
from medis.optics import check_sampling
from medis.utils import dprint


# def ao(wf, WFS_map, theta):
#     if sp.closed_loop:
#         deformable_mirror(wf, WFS_map, theta)
#     else:
#         WFS_map = open_loop_wfs(wf)  # overwrite WFS_map
#         # dprint(f"WFS_ma.shape = {WFS_map.shape}")
#         deformable_mirror(wf, WFS_map, theta)
#

################################################################################
# Deformable Mirror
################################################################################
def deformable_mirror(wf, WFS_map, iter, plane_name=None):
    """
    combine different DM actuator commands into single map to send to prop_dm

    prop_dm needs an input map of n_actuators x n_actuators in units of actuator command height. quick_ao will handle
    the conversion to actuator command height, and the CDI probe must be scaled in cdip.probe_amp in params in
    units of m. Each subroutine is also responsible for creating a map of n_actuators x n_actuators spacing. prop_dm
    handles the resampling of this map onto the wavefront, including the influence function. Its some wizardry that
    happens in c, and presumably it is taken care of so you don't have to worry about it.

    In the call to proper.prop_dm, we apply the flag tp.fit_dm, which switches between two 'modes' of proper's DM
    surface fitting. If FALSE, the DM is driven to the heights specified by dm_map, and the influence function will
    act on these heights to define the final surface shape applied to the DM, which may differ substantially from
    the initial heights specified by dm_map. If TRUE, proper will iterate applying the influence function to the
    input heights, and adjust the heights until the difference between the influenced-map and input map meets some
    proper-defined convergence criterea. Setting tp.fit_dm=TRUE will obviously slow down the code, but will (likely)
    more accurately represent a well-calibrated DM response function.

    much of this code copied over from example from Proper manual on pg 94

    :param wf: single wavefront
    :param WFS_map: wavefront sensor map, should be in units of phase delay
    :param iter: the current index of iteration (which timestep this is)
    :param plane_name: name of plane (should be 'woofer' or 'tweeter' for best functionality
    :return: nothing is returned, but the probe map has been applied to the DM via proper.prop_dm
    """
    # AO Actuator Count from DM Type
    if plane_name == 'tweeter' and hasattr('tp','act_tweeter'):
        nact = tp.act_tweeter
    elif plane_name == 'woofer' and hasattr('tp','act_woofer'):
        nact = tp.act_woofer
    else:
        nact = tp.ao_act

    # DM Coordinates
    nact_across_pupil = nact - 2  # number of full DM actuators across pupil (oversizing DM extent)
    dm_xc = (nact / 2) - 0.5  # The location of the optical axis (center of the wavefront) on the DM in
    dm_yc = (nact / 2) - 0.5  # actuator units. First actuator is centered on (0.0, 0.0). The 0.5 is a
    #  parameter introduced/tuned by Rupert to remove weird errors (address this).
    # KD verified this needs to be here or else suffer weird errors 9/19
    # TODO address/remove the 0.5 in DM x,y coordinates

    ############################
    # Creating DM Surface Map
    ############################
    d_beam = 2 * proper.prop_get_beamradius(wf)  # beam diameter
    act_spacing = d_beam / nact_across_pupil  # actuator spacing [m]
    # map_spacing = proper.prop_get_sampling(wfo.wf_collection[iw,0])

    #######
    # AO
    #######
    dm_map = quick_ao(wf, nact, WFS_map[wf.iw])

    #######
    # CDI
    ######
    if cdip.use_cdi:
        # dprint(f"Applying CDI probe, lambda = {wfo.wsamples[iw]*1e9:.2f} nm")
        probe = cdi.CDIprobe(iter)
        # Add Probe to DM map
        dm_map = dm_map + probe

    #########################
    # Applying Piston Error
    #########################
    if tp.piston_error:
        mean_dm_map = np.mean(np.abs(dm_map))
        var = 1e-4  # 1e-11
        dm_map = dm_map + np.random.normal(0, var, (dm_map.shape[0], dm_map.shape[1]))

    #########################
    # proper.prop_dm
    #########################
    proper.prop_dm(wf, dm_map, dm_xc, dm_yc, act_spacing, FIT=tp.fit_dm)  #
    # proper.prop_dm(wfo, dm_map, dm_xc, dm_yc, N_ACT_ACROSS_PUPIL=nact, FIT=True)  #

    # check_sampling(0, wfo, "E-Field after DM", getframeinfo(stack()[0][0]), units='um')  # check sampling from optics.py

    return


################################################################################
# Ideal AO
################################################################################
def quick_ao(wf, nact, WFS_map):
    """
    calculate the offset map to send to the DM from the WFS map

    The main idea is to apply the DM only to the region of the wavefront that contains the beam. The phase map from
    the wfs saved the whole wavefront, so that must be cropped. During the wavefront initialization in
    wavefront.initialize_proper, the beam ratio set in sp.beam_ratio is scaled per wavelength (to achieve constant
    sampling sto create white light images), so the cropped value must also be scaled by wavelength. Note, beam ratio
    is scaled differently depending on if sp.focused_sys is True or not. See params-->sp.focused_sys and Proper
    manual pg 36 for more info.

    Then, we interpolate the cropped beam onto a grid of (n_actuators,n_actuators), such that the DM can apply a
    actuator height to each represented actuator, not a over or sub-sampled form. If the number of actuators is low
    compared to the number of samples on the beam, you should anti-alias the WFS map via a lowpass filter before
    interpolating. There is a discrepancy between the sampling of the wavefront at this location (the size you cropped)
    vs the size of the DM. proper.prop_dm handles this, so just plug in the n_actuator sized DM map with specified
    parameters, and assume that prop_dm handles the resampling correctly via the spacing or n_act_across_pupil flag.
    FYI the resampling is done via a c library you installed/compiled when installing proper.

    The WFS map is a map of real values in units of phase delay in radians. However, the AO map that gets passed to
    proper.prop_dm wants input in nm height of each actuator. Therefore, you need to convert the phase delay to
    a DM height. For the ideal AO, you would do this individually for each wavelength. However, for a 'real' AO system
    you do this for the median wavelength. You also need to account for a factor of 2, since the DM is modeled as
    a mirror so it travels the length of the phase delay twice.

    much of this code copied over from example from Proper manual on pg 94

    :param wfo: wavefront object created by optics.Wavefronts() [n_wavelengths, n_objects] of tp.gridsize x tp.gridsize
    :param WFS_map: returned from quick_wfs (as of Aug 2019, its an idealized image)
    :return: ao_map: map of DM actuator command heights in units of m
    """

    nact_across_pupil = nact-2          # number of full DM actuators across pupil (oversizing DM extent)
                                        # Note: oversample by 2 actuators hardcoded here, check if this is appropriate 
    
    ############################
    # Creating AO Surface Map
    ############################
    d_beam = 2 * proper.prop_get_beamradius(wf)  # beam diameter
    act_spacing = d_beam / nact_across_pupil  # actuator spacing [m]
    # map_spacing = proper.prop_get_sampling(wfo.wf_collection[iw,0])

    ###################################
    # Cropping the Beam from WFS map
    ###################################
    # cropping here by beam_ratio rather than d_beam is valid since the beam size was initialized
    #  using the scaled beam_ratios when the wfo was created
    # dprint(f"{WFS_map[0,0,0]}")
    ao_map = WFS_map[
             sp.grid_size//2 - np.int_(wf.beam_ratio*sp.grid_size//2):
             sp.grid_size//2 + np.int_(wf.beam_ratio*sp.grid_size//2)+1,
             sp.grid_size//2 - np.int_(wf.beam_ratio*sp.grid_size//2):
             sp.grid_size//2 + np.int_(wf.beam_ratio*sp.grid_size//2)+1]

    ########################################################
    # Interpolating the WFS map onto the actuator spacing
    # (tp.nact,tp.nact)
    ########################################################
    # Lowpass Filter- prevents aliasing; uses Gaussian filter
    nyquist_dm = tp.ao_act/2 * act_spacing  # [m]
    sigma = [nyquist_dm/2.355, nyquist_dm/2.355]  # assume we want sigma to be twice the HWHM
    ao_map = ndimage.gaussian_filter(ao_map, sigma=sigma, mode='nearest')

    f = interpolate.interp2d(range(ao_map.shape[0]), range(ao_map.shape[0]), ao_map, kind='cubic')
    ao_map = f(np.linspace(0,ao_map.shape[0],nact), np.linspace(0,ao_map.shape[0], nact))
    # dm_map = proper.prop_magnify(dm_map, map_spacing / act_spacing, nact)

    ################################################
    # Converting phase delay to DM actuator height
    ################################################
    # Apply the inverse of the WFS image to the DM, so use -dm_map (dm_map is in phase units, divide by k=2pi/lambda)
    surf_height = proper.prop_get_wavelength(wf) / (4 * np.pi)  # [m/rad]
    ao_map = -ao_map * surf_height  # Converts DM map to units of [m] of actuator heights

    return ao_map
            

def open_loop_wfs(wfo):
    """
    saves the unwrapped phase [arctan2(imag/real)] of the wfo.wf_collection at each wavelength

    It is an idealized image (exact copy) of the wavefront phase per wavelength. Only the map for the first object
    (the star) is saved

    #TODO the way this is saved for naming the WFS_map is going to break if you want to do closed loop WFS on a
    #woofer-tweeter system

    :param wfo: wavefront object
    :return: array containing only the unwrapped phase delay of the wavefront; shape=[n_wavelengths], units=radians
    """
    star_wf = wfo.wf_collection[:, 0]
    WFS_map = np.zeros((len(star_wf), sp.grid_size, sp.grid_size))

    for iw in range(len(star_wf)):
        WFS_map[iw] = unwrap_phase(proper.prop_get_phase(star_wf[iw]))

    if 'open_loop_wfs' in sp.save_list or sp.closed_loop:
        wfo.save_plane(location='WFS_map')

    return WFS_map

################################################################################
# Full AO
################################################################################
# not implemented. Full AO implies a time delay, and maybe non-ideal WFS
