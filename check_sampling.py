"""
check the params entered to mm_params for given telescope settings for correct sampling
KD 8/13/19

According to the Proper manual:
    tp.beam_ratio = tp.enterance_d/ init_grid_width
    where init_grid_width is the initial grid width (diameter) in meters
Thus
    init_grid_width = tp.enterence_d / tp.beam_ratio

The sampling of the beam is defined by
    sampling = grid_width / tp.grid_size
    :keyword
    sampling = tp.enterence_d * tp.grid_size / tp.beam_ratio
    where grid_width here is the initial grid width

"""
import numpy as np
from mm_params import tp

#######################################
# Definitions from inside mini-medis
#######################################
# Basics-not imported
# tp.enterance_d = 8.2  # m
# tp.beam_ratio = .18
# tp.grid_size = 512

# From Params Buried in mini-medis
legs_frac = 0.05  # m
Fnum = 12.6  # focal ratio of the beam as it approaches the focus
lmbda = 800e-6  # m  wavelength of interest

#######################
# Initial Sampling
######################
init_grid_width = tp.enterance_d / tp.beam_ratio
init_sampling = init_grid_width / tp.grid_size
init_npix_on_beam = tp.enterance_d / init_sampling
print(f"Initial Grid Width = {init_grid_width:.2f} m")

#################################
# Checking Sampling of Spiders
################################
spider_width = tp.enterance_d * legs_frac
npix_on_spiders = spider_width / init_sampling
print(f"Number of pixels across the spiders = {npix_on_spiders}")
print("********************************")

###################
# Ideal Sampling
###################
"""
see proper manual pg 36 for definitions

init_grid_width is dependant on chosen/user-defined beam ratio. In order to determine what a "good" one would be,
first choose a grid_width that is significantly larger than the entrance diameter, such that the beam is only 
resolved by a few pixels. This ensures there is sufficient zero-padding of the pupil to avoid FFT effects, and you
can check the sampling of the spiders with the code above. There is a trade-off between sampling in the pupil and 
the image planes, so it is best to only choose a beam ratio that barely resolves the smallest features of the aperture 
(spiders), in order to get the best resolution of the image plane. 
"""
print(f"Ideal Values")
grid_width = 30  # m
samp_good = Fnum*lmbda*tp.enterance_d / grid_width
samp_nyq = Fnum*lmbda/2
print(f"Ideal Sampling is {samp_good:.6f} m/pix \nNyquist Sampling is {samp_nyq:.6f} m/pix")

# selecting beam ratio
br_good = tp.enterance_d/(samp_good*tp.grid_size)
br_nyq = tp.enterance_d/samp_nyq/tp.grid_size
print(f"Good starter beam ratio is {br_good} \nNyquist beam ratio is {br_nyq}")

###########################################
# Beam Size and Grid Width at other Plane
###########################################
final_sampling = 0.212727  # m/pix
final_grid_width = final_sampling * tp.grid_size  # m
final_beam_size = final_grid_width * tp.beam_ratio  # m
final_npix_on_beam = final_beam_size / final_sampling  # pixels
