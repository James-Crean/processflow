#!/bin/csh

#
# Template driver script to generate coupled diagnostics on aims4 (LLNL machine)
#
# Basic usage:
#       0. Make sure you do not point to any particular python or conda environment
#          in your .cshrc or .bashrc
#	1. To activate the environment, set this in your .bashrc (or .cshrc):
#		a. export NCL_PATH= /usr/local/src/NCL-6.3.0/bin
#		b. export CONDA_PATH=/export/veneziani1/miniconda2.7/bin
#               c. export NCO_PATH=/export/zender1/bin
#		d. export PATH=${CONDA_PATH}\:${NCL_PATH}\:${NCO_PATH}\:${PATH}
#               e. export LD_LIBRARY_PATH='/export/zender1/lib'\:${LD_LIBRARY_PATH}
#       2. copy this template to something like run_AIMS_$user.csh
#       3. open run_AIMS_$user.csh and set user defined, case-specific variables
#       4. execute: csh run_AIMS_$user.csh
#       5. access the html link by using username/password equalt to acme/acme, respectively

# Meaning of acronyms/words used in variable names below:
#	test:		Test case
#	ref:		Reference case
#	ts: 		Time series; e.g. test_begin_yr_ts, here ts refers to time series
#	climo: 		Climatology
#	begin_yr: 	Model year to start analysis
#	end_yr:		Model year to end analysis
#       condense:       Create a new file for each variable with time series data for that variable.
#                       This is used to create climatology (if not pre-computed) and in generating time series plots
#	archive_dir:	Location of model generated output directory
#	scratch_dir:	Location of directory where the user wants to store files generated by the diagnostics.
#			This includes climos, remapped climos, condensed files and data files used for plotting.
#       short_term_archive:     Adds /atm/hist after the casename. If the data sits in a different structure, add it after
#       the casename in test_casename

set projdir =                  		%%coupled_project_dir%%

# USER DEFINED CASE SPECIFIC VARIABLES TO SPECIFY (REQUIRED)

# Main directory where all analysis output is stored
# (e.g., plots will go in a specific subdirectory of $output_base_dir,
# as will log files, generated climatologies, etc)
setenv output_base_dir                  %%output_base_dir%%

# Test case variables, for casename, add any addendums like /run or /atm/hist
setenv test_casename                    %%test_casename%%
setenv test_native_res                  %%test_native_res%%
# one of the supported MPAS mesh names (e.g. oEC60to30v1, oEC60to30v3, oRRS18to6v1)
# NB: this may change with a different choice of test_casename!
setenv test_archive_dir                 %%test_archive_dir%%
setenv test_short_term_archive          0
setenv test_begin_yr_climo              %%test_begin_yr_climo%%
setenv test_end_yr_climo                %%test_end_yr_climo%%
setenv test_begin_yr_ts                 %%test_begin_yr_ts%%
setenv test_end_yr_ts                   %%test_end_yr_ts%%
setenv test_begin_yr_climateIndex_ts	1
setenv test_end_yr_climateIndex_ts	9999
setenv test_mpas_mesh_name              oEC60to30v1


# Atmosphere switches (True(1)/False(0)) to condense variables, compute climos, remap climos and condensed time series file
# If no pre-processing is done (climatology, remapping), all the switches below should be 1
setenv test_compute_climo		1
setenv test_remap_climo			1
setenv test_condense_field_climo	1
setenv test_condense_field_ts		1
setenv test_remap_ts			1

# Reference case variables (similar to test_case variables)
setenv ref_case			        obs
setenv ref_archive_dir                  %%ref_archive_dir%%
#setenv ref_case			20160520.A_WCYCL1850.ne30_oEC.edison.alpha6_01
#setenv ref_archive_dir 		/scratch1/scratchdirs/golaz/ACME_simulations

# ACMEv0 ref_case info for ocn/ice diags
#  IMPORTANT: the ACMEv0 model data MUST have been pre-processed.
#  If this pre-processed data is not available, set ref_case_v0 to None.
#setenv ref_case_v0                     None
setenv ref_case_v0                      B1850C5_ne30_v0.4
setenv ref_archive_v0_ocndir            /p/cscratch/acme/data/${ref_case_v0}/ocn/postprocessing
setenv ref_archive_v0_seaicedir         /p/cscratch/acme/data/${ref_case_v0}/ice/postprocessing

#The following are ignored if ref_case is obs
setenv ref_native_res                   None
setenv ref_short_term_archive           None
setenv ref_begin_yr_climo               None
setenv ref_end_yr_climo                 None
setenv ref_begin_yr_ts                  None
setenv ref_end_yr_ts                    None
setenv ref_begin_yr_climateIndex_ts	1
setenv ref_end_yr_climateIndex_ts	9999

setenv ref_condense_field_climo         1
setenv ref_condense_field_ts            1
setenv ref_compute_climo                1
setenv ref_remap_climo                  1
setenv ref_remap_ts                     1

# Select sets of diagnostics to generate (False = 0, True = 1)
setenv generate_atm_diags 		1
setenv generate_ocnice_diags 		%%run_ocean%%

# The following ocn/ice diagnostic switches are ignored if generate_ocnice_diags is set to 0
setenv generate_ohc_trends 		1
setenv generate_sst_trends 		1
setenv generate_sst_climo 		1
setenv generate_sss_climo               1
setenv generate_mld_climo               1
setenv generate_moc 			1
setenv generate_nino34 			1
setenv generate_seaice_trends 		1
setenv generate_seaice_climo 		1

# Other diagnostics not working currently, work in progress
setenv generate_mht 			0

# Generate standalone html file to view plots on a browser, if required
setenv generate_html 			1
###############################################################################################

# OTHER VARIABLES (NOT REQUIRED TO BE CHANGED BY THE USER - DEFAULTS SHOULD WORK, USER PREFERENCE BASED CHANGES)

# Set paths to scratch, logs and plots directories
setenv test_scratch_dir                 $output_base_dir/$test_casename.test.pp
setenv ref_scratch_dir                  $output_base_dir/$ref_case.test.pp
setenv plots_dir                        $output_base_dir/coupled_diagnostics_${test_casename}-$ref_case
setenv log_dir                          $output_base_dir/coupled_diagnostics_${test_casename}-$ref_case.logs

# Set atm specific paths to mapping and data files locations
setenv remap_files_dir                  %%remap_files_dir%%
setenv GPCP_regrid_wgt_file             %%GPCP_regrid_wgt_file%%
setenv CERES_EBAF_regrid_wgt_file       %%CERES_EBAF_regrid_wgt_file%%
setenv ERS_regrid_wgt_file              %%ERS_regrid_wgt_file%%

# Set ocn/ice specific paths to mapping and region masking file locations
#     remap from MPAS mesh to regular 0.5degx0.5deg grid
#     NB: if this file does not exist, it will be generated by the analysis
setenv mpas_remapfile                   %%mpas_remapfile%%#     MPAS-O region mask files containing masking information for the Atlantic basin
#     NB: this file, instead, *needs* to be present
setenv mpaso_regions_file               %%mpaso_regions_file%%

# Set ocn/ice specific paths to data file names and locations
setenv obs_ocndir                       %%obs_ocndir%%
setenv obs_seaicedir                    %%obs_seaicedir%%
setenv obs_sstdir                       %%obs_sstdir%%
setenv obs_sstdir                       $obs_ocndir/SST
setenv obs_sssdir                       $obs_ocndir/SSS
setenv obs_mlddir                       $obs_ocndir/MLD
setenv obs_ninodir                      $obs_ocndir/Nino
setenv obs_iceareaNH                    $obs_seaicedir/IceArea_timeseries/iceAreaNH_climo.nc
setenv obs_iceareaSH                    $obs_seaicedir/IceArea_timeseries/iceAreaSH_climo.nc
setenv obs_icevolNH                     $obs_seaicedir/PIOMAS/PIOMASvolume_monthly_climo.nc
setenv obs_icevolSH                     none

# Location of website directory to host the webpage
setenv www_dir                          %%web_dir%%
##############################################################################
########### USER SHOULD NOT NEED TO CHANGE ANYTHING HERE ONWARDS #############

setenv coupled_diags_home               %%coupled_diags_home%%

# PUT THE PROVIDED CASE INFORMATION IN CSH ARRAYS TO FACILITATE READING BY OTHER SCRIPTS
$coupled_diags_home/csh_scripts/setup.csh

# RUN DIAGNOSTICS
if ($generate_atm_diags == 1) then
        # Check whether requested files for computing climatologies are available
        set rpointer_file = ${test_archive_dir}/${test_casename}/run/rpointer.atm
        set year_max = `grep -m 1 -Eo '\<[0-9]{4}\>' ${rpointer_file} | awk '{print $1-1}'`
        if (${test_end_yr_climo} <= ${year_max}) then
          $coupled_diags_home/ACME_atm_diags.csh
          set atm_status = $status
        else
          echo "Requested test_end_yr_climo is larger than the maximum simulation year. Exiting atm diagnostics..."
          echo "Please set test_end_yr_climo <= ${year_max}"
          set atm_status = 0
        endif
else
        set atm_status = 0
endif

if ($generate_ocnice_diags == 1) then
        # Check whether requested files for computing climatologies are available
        set rpointer_file = ${test_archive_dir}/${test_casename}/run/rpointer.ocn
        set year_max = `grep -m 1 -Eo '\<[0-9]{4}\>' ${rpointer_file} | awk '{print $1-1}'`
        if (${test_end_yr_climo} <= ${year_max}) then
          $coupled_diags_home/ACME_ocnice_diags.csh
          set ocnice_status = $status
        else
          echo "Requested test_end_yr_climo is larger than the maximum simulation year. Exiting ocn/ice diagnostics..."
          echo "Please set test_end_yr_climo <= ${year_max}"
          set ocnice_status = 0
        endif
else
        set ocnice_status = 0
endif

# GENERATE HTML PAGE IF ASKED
echo
echo "Status of atmospheric diagnostics, 0 implies success or not invoked:" $atm_status
echo "Status of ocean/ice diagnostics, 0 implies success or not invoked:" $ocnice_status

if ($atm_status == 0 || $ocnice_status == 0) then
        source $log_dir/case_info.temp

        set n_cases = $#case_set

        @ n_test_cases = $n_cases - 1

        foreach j (`seq 1 $n_test_cases`)

                if ($generate_html == 1) then
                        csh $coupled_diags_home/csh_scripts/generate_html_index_file.csh    $j \
                                                                        $plots_dir \
                                                                        $www_dir
                endif
        end
else
        echo
        echo Neither atmospheric nor ocn/ice diagnostics were successful. HTML page not generated!
        echo
        echo
endif