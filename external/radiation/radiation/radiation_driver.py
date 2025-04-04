import numpy as np
import warnings

from .types import DTYPE_INT
from .radphysparam import ictmflg, ivflip
from .phys_const import con_eps, con_epsm1, con_rocp, con_fvirt, con_rog, con_epsq
from .funcphys import fpvs

from .radiation_astronomy import AstronomyClass
from .radiation_aerosols import AerosolClass
from .radiation_clouds import CloudClass
from .radiation_gases import GasClass
from .radiation_sfc import SurfaceClass
from .radlw import RadLWClass
from .radsw import RadSWClass


class RadiationDriver:

    VTAGRAD = "NCEP-Radiation_driver    v5.2  Jan 2013"

    QMIN = 1.0e-10
    QME5 = 1.0e-7
    QME6 = 1.0e-7
    EPSQ = 1.0e-12

    # lower limit of toa pressure value in mb
    prsmin = 1.0e-6

    # optional extra top layer on top of low ceiling models
    # LTP=0: no extra top layer
    LTP = 0  # no extra top layer

    # control flag for extra top layer
    lextop = LTP > 0

    def __init__(
        self,
        si,
        NLAY,
        rank,
        iemsflg,
        ioznflg,
        ictmflg,
        isolar,
        ico2flg,
        iaerflg,
        ialbflg,
        ivflip,
        iovrsw,
        iovrlw,
        isubcsw,
        isubclw,
        lcnorm,
        aerosol_dict,
        semis_data,
        do_test=False,
    ):
        self.itsfc = iemsflg / 10  # sfc air/ground temp control
        self.loz1st = ioznflg == 0  # first-time clim ozone data read flag
        self.month0 = 0
        self.iyear0 = 0
        self.monthd = 0
        self.isolar = isolar

        # -# Initialization
        #  --- ...  astronomy initialization routine
        self.sol = AstronomyClass(isolar)
        #  --- ...  aerosols initialization routine
        self.aer = AerosolClass(NLAY, iaerflg, ivflip, aerosol_dict)
        #  --- ...  co2 and other gases initialization routine
        self.gas = GasClass(rank, ioznflg, ico2flg, ictmflg)
        #  --- ...  surface initialization routine
        self.sfc = SurfaceClass(ialbflg, iemsflg, semis_data)
        #  --- ...  cloud initialization routine
        self.cld = CloudClass(si, NLAY, ivflip, iovrsw, iovrlw, lcnorm)
        #  --- ...  lw radiation initialization routine
        self.rlw = RadLWClass(iovrlw, isubclw)
        #  --- ...  sw radiation initialization routine
        self.rsw = RadSWClass(iovrsw, isubcsw)

        if do_test:
            sol_dict = self.sol.return_initdata()
            aer_dict = self.aer.return_initdata()
            gas_dict = self.gas.return_initdata()
            sfc_dict = self.sfc.return_initdata()
            cld_dict = self.cld.return_initdata()
            rlw_dict = self.rlw.return_initdata()
            rsw_dict = self.rsw.return_initdata()

            return aer_dict, sol_dict, gas_dict, sfc_dict, cld_dict, rlw_dict, rsw_dict

    @classmethod
    def validate(
        cls,
        isolar,
        ictmflg,
        iovrsw,
        iovrlw,
        isubcsw,
        isubclw,
        iaerflg,
        ioznflg,
        ico2flg,
        ialbflg,
        iemsflg,
        imp_physics,
        icldflg,
        lcrick,
        lcnorm,
        lnoprec,
        uni_cld,
        effr_in,
    ):

        print("NEW RADIATION PROGRAM STRUCTURES BECAME OPER. May 01 2007")
        print(cls.VTAGRAD)  # print out version tag
        print(" ")
        print(f"- Selected Control Flag settings: ICTMflg={ictmflg}")
        print(f"  ISOLar ={isolar}, ICO2flg={ico2flg}, IAERflg={iaerflg}")
        print(f"  IALBflg={ialbflg}, IEMSflg={iemsflg}, ICLDflg={icldflg}")
        print(f"  IMP_PHYSICS={imp_physics}, IOZNflg={ioznflg}")
        print(f"  IVFLIP={ivflip}, IOVRSW={iovrsw}, IOVRLW={iovrlw}")
        print(f"  ISUBCSW={isubcsw}, ISUBCLW={isubclw}")
        print(f"  LCRICK={lcrick}, LCNORM={lcnorm}, LNOPREC={lnoprec}")
        print(f"  LTP ={cls.LTP}, add extra top layer ={cls.lextop}")
        print(" ")

        if ictmflg == 0 or ictmflg == -2:
            print("Data usage is limited by initial condition!")
            print("No volcanic aerosols")

        if (iovrsw not in [0, 1, 3]) or (iovrlw not in [0, 1, 3]):
            raise ValueError(
                "Implemented overlap options in Python port of radiation "
                "scheme are 0 (random overlap), 1 (maximum-random overlap), "
                "and 3 (decorrelation-length overlap)."
                f" Got iovrsw={iovrsw}, iovrlw={iovrlw}."
            )

        if isubclw == 0:
            print(
                f"- ISUBCLW={isubclw}, No McICA, use grid ",
                f"averaged cloud in LW radiation",
            )
            raise ValueError(f"- ERROR!!! ISUBCLW={isubclw}, is not a valid option")

        if isubclw == 1:
            print(
                "- ISUBCLW={isubclw}, Use McICA with fixed ",
                "permutation seeds for LW random number generator",
            )
            raise ValueError(f"- ERROR!!! ISUBCLW={isubclw}, is not a valid option")

        if isubclw == 2:
            print(
                f"- ISUBCLW={isubclw}, Use McICA with random ",
                f"permutation seeds for LW random number generator",
            )

        else:
            raise ValueError(f"- ERROR!!! ISUBCLW={isubclw}, is not a valid option")

        if isubcsw == 0:
            print(
                "- ISUBCSW={isubcsw}, No McICA, use grid ",
                "averaged cloud in SW radiation",
            )
            raise ValueError(f"- ERROR!!! ISUBCSW={isubcsw}, is not a valid option")

        if isubcsw == 1:
            print(
                f"- ISUBCSW={isubcsw}, Use McICA with fixed ",
                "permutation seeds for SW random number generator",
            )
            raise ValueError(f"- ERROR!!! ISUBCSW={isubcsw}, is not a valid option")

        if isubcsw == 2:
            print(
                f"- ISUBCSW={isubcsw}, Use McICA with random ",
                "permutation seeds for SW random number generator",
            )
        else:
            raise ValueError(f"- ERROR!!! ISUBCSW={isubcsw}, is not a valid option")

        if isubcsw != isubclw:
            warnings.warn(
                "- *** Notice *** ISUBCSW /= ISUBCLW !!!", f"{isubcsw}, {isubclw}"
            )

        if uni_cld:
            raise ValueError(f"uni_cld = True Not implemented")

        if effr_in:
            raise ValueError(f"effr_in = True Not implemented")

        AstronomyClass.validate(isolar)
        AerosolClass.validate(iaerflg)
        GasClass.validate(ioznflg, ico2flg, ictmflg)
        SurfaceClass.validate(ialbflg, iemsflg)
        CloudClass.validate(imp_physics, icldflg)
        RadLWClass.validate(iovrlw, isubclw, icldflg)
        RadSWClass.validate(iovrsw, isubcsw, icldflg)

    @property
    def solar_constant(self):
        return self.sol.solcon

    def radupdate(
        self,
        idate,
        jdate,
        deltsw,
        deltim,
        lsswr,
        kprfg,
        idxcg,
        cmixg,
        denng,
        cline,
        solar_data,
        gas_data,
        rank,
        do_test=False,
    ):
        # =================   subprogram documentation block   ================ !
        #                                                                       !
        # subprogram:   radupdate   calls many update subroutines to check and  !
        #   update radiation required but time varying data sets and module     !
        #   variables.                                                          !
        #                                                                       !
        # usage:        call radupdate                                          !
        #                                                                       !
        # attributes:                                                           !
        #   language:  fortran 90                                               !
        #   machine:   ibm sp                                                   !
        #                                                                       !
        #  ====================  definition of variables  ====================  !
        #                                                                       !
        # input parameters:                                                     !
        #   idate(8)       : ncep absolute date and time of initial condition   !
        #                    (yr, mon, day, t-zone, hr, min, sec, mil-sec)      !
        #   jdate(8)       : ncep absolute date and time at fcst time           !
        #                    (yr, mon, day, t-zone, hr, min, sec, mil-sec)      !
        #   deltsw         : sw radiation calling frequency in seconds          !
        #   deltim         : model timestep in seconds                          !
        #   lsswr          : logical flags for sw radiation calculations        !
        #   rank           : print control flag                                 !
        #                                                                       !
        #  outputs:                                                             !
        #   slag           : equation of time in radians                        !
        #   sdec, cdec     : sin and cos of the solar declination angle         !
        #   solcon         : sun-earth distance adjusted solar constant (w/m2)  !
        #                                                                       !
        #  external module variables:                                           !
        #   isolar   : solar constant cntrl  (in module physparam)               !
        #              = 0: use the old fixed solar constant in "physcon"       !
        #              =10: use the new fixed solar constant in "physcon"       !
        #              = 1: use noaa ann-mean tsi tbl abs-scale with cycle apprx!
        #              = 2: use noaa ann-mean tsi tbl tim-scale with cycle apprx!
        #              = 3: use cmip5 ann-mean tsi tbl tim-scale with cycl apprx!
        #              = 4: use cmip5 mon-mean tsi tbl tim-scale with cycl apprx!
        #   ictmflg  : =yyyy#, external data ic time/date control flag          !
        #              =   -2: same as 0, but superimpose seasonal cycle        !
        #                      from climatology data set.                       !
        #              =   -1: use user provided external data for the          !
        #                      forecast time, no extrapolation.                 !
        #              =    0: use data at initial cond time, if not            !
        #                      available, use latest, no extrapolation.         !
        #              =    1: use data at the forecast time, if not            !
        #                      available, use latest and extrapolation.         !
        #              =yyyy0: use yyyy data for the forecast time,             !
        #                      no further data extrapolation.                   !
        #              =yyyy1: use yyyy data for the fcst. if needed, do        !
        #                      extrapolation to match the fcst time.            !
        #                                                                       !
        #  module variables:                                                    !
        #   loz1st   : first-time clim ozone data read flag                     !
        #                                                                       !
        #  subroutines called: sol_update, aer_update, gas_update               !
        #                                                                       !
        #  ===================================================================  !
        #

        # -# Set up time stamp at fcst time and that for green house gases
        # (currently co2 only)
        # --- ...  time stamp at fcst time

        iyear = jdate[0]
        imon = jdate[1]
        iday = jdate[2]
        ihour = jdate[4]

        #  --- ...  set up time stamp used for green house gases (** currently co2 only)

        if ictmflg == 0 or ictmflg == -2:  # get external data at initial condition time
            kyear = idate[0]
            kmon = idate[1]
            kday = idate[2]
            khour = idate[4]
        else:  # get external data at fcst or specified time
            kyear = iyear
            kmon = imon
            kday = iday
            khour = ihour

        if self.month0 != imon:
            lmon_chg = True
            self.month0 = imon
        else:
            lmon_chg = False

        # -# Call module_radiation_astronomy::sol_update(), yearly update, no
        # time interpolation.
        if lsswr:
            if self.isolar == 0 or self.isolar == 10:
                lsol_chg = False
            elif self.iyear0 != iyear:
                lsol_chg = True
            else:
                lsol_chg = self.isolar == 4 and lmon_chg

            self.iyear0 = iyear

            slag, sdec, cdec, solcon = self.sol.sol_update(
                jdate, kyear, deltsw, deltim, lsol_chg, rank, solar_data
            )

        # Call module_radiation_aerosols::aer_update(), monthly update, no
        # time interpolation
        if lmon_chg:
            self.aer.aer_update(iyear, imon, rank, kprfg, idxcg, cmixg, denng, cline)

        # -# Call co2 and other gases update routine:
        # module_radiation_gases::gas_update()
        if self.monthd != kmon:
            self.monthd = kmon
            lco2_chg = True
        else:
            lco2_chg = False

        self.gas.gas_update(kyear, kmon, kday, khour, self.loz1st, lco2_chg, gas_data)

        if self.loz1st:
            self.loz1st = False

        if do_test:
            soldict = {"slag": slag, "sdec": sdec, "cdec": cdec, "solcon": solcon}
            aerdict = self.aer.return_updatedata()
            gasdict = self.gas.return_updatedata()

            return soldict, aerdict, gasdict

    def GFS_radiation_driver(
        self,
        gfs_physics_control,
        solcon,
        solhr,
        Statein,
        Sfcprop,
        Coupling,
        Grid,
        Tbd,
        Radtend,
        Diag,
        randomdict,
        lwdict,
        swdict,
    ):

        return self._GFS_radiation_driver(
            gfs_physics_control,
            solcon,
            solhr,
            Statein,
            Sfcprop,
            Grid,
            randomdict,
            lwdict,
            swdict,
        )

    def _GFS_radiation_driver(
        self,
        gfs_physics_control,
        solcon,
        solhr,
        Statein,
        Sfcprop,
        Grid,
        randomdict,
        lwdict,
        swdict,
    ):
        # --- set commonly used integers
        LM = gfs_physics_control.config.levr
        LEVS = gfs_physics_control.config.levs
        IM = Grid["xlon"].shape[0]
        NTRAC = (
            gfs_physics_control.ntrac
        )  # tracers in grrad strip off sphum - start tracer1(2:NTRAC)
        ntcw = gfs_physics_control.ntcw
        ntiw = gfs_physics_control.ntiw
        ntrw = gfs_physics_control.ntrw
        ntsw = gfs_physics_control.ntsw
        ntgl = gfs_physics_control.ntgl
        ncndl = min(gfs_physics_control.config.ncnd, 4)

        LP1 = LM + 1  # num of in/out levels

        tskn = np.zeros(IM)
        tsfa = np.zeros(IM)
        tsfg = np.zeros(IM)
        tem1d = np.zeros(IM)
        alb1d = np.zeros(IM)
        idxday = np.zeros(IM, dtype=DTYPE_INT)

        plvl = np.zeros((IM, gfs_physics_control.config.levr + self.LTP + 1))
        tlvl = np.zeros((IM, gfs_physics_control.config.levr + self.LTP + 1))
        tem2db = np.zeros((IM, gfs_physics_control.config.levr + self.LTP + 1))

        plyr = np.zeros((IM, gfs_physics_control.config.levr + self.LTP))
        tlyr = np.zeros((IM, gfs_physics_control.config.levr + self.LTP))
        olyr = np.zeros((IM, gfs_physics_control.config.levr + self.LTP))
        qlyr = np.zeros((IM, gfs_physics_control.config.levr + self.LTP))
        rhly = np.zeros((IM, gfs_physics_control.config.levr + self.LTP))
        tvly = np.zeros((IM, gfs_physics_control.config.levr + self.LTP))
        delp = np.zeros((IM, gfs_physics_control.config.levr + self.LTP))
        qstl = np.zeros((IM, gfs_physics_control.config.levr + self.LTP))
        cldcov = np.zeros((IM, gfs_physics_control.config.levr + self.LTP))
        deltaq = np.zeros((IM, gfs_physics_control.config.levr + self.LTP))
        cnvc = np.zeros((IM, gfs_physics_control.config.levr + self.LTP))
        cnvw = np.zeros((IM, gfs_physics_control.config.levr + self.LTP))
        dz = np.zeros((IM, gfs_physics_control.config.levr + self.LTP))
        prslk1 = np.zeros((IM, gfs_physics_control.config.levr + self.LTP))
        tem2da = np.zeros((IM, gfs_physics_control.config.levr + self.LTP))

        tracer1 = np.zeros((IM, gfs_physics_control.config.levr + self.LTP, NTRAC))
        ccnd = np.zeros(
            (
                IM,
                gfs_physics_control.config.levr + self.LTP,
                min(4, gfs_physics_control.config.ncnd),
            )
        )

        cldtausw = np.zeros((IM, gfs_physics_control.config.levr + self.LTP))

        Coupling = {}
        scmpsw = {}
        Diag = {}
        Radtend = {}
        Radtend["coszen"] = np.zeros(IM)
        Radtend["coszdg"] = np.zeros(IM)
        Radtend["htrsw"] = np.zeros((IM, gfs_physics_control.config.levs))
        Radtend["swhc"] = np.zeros((IM, gfs_physics_control.config.levs))
        Radtend["lwhc"] = np.zeros((IM, gfs_physics_control.config.levs))
        Radtend["semis"] = np.zeros(IM)
        Radtend["tsflw"] = np.zeros(IM)
        Radtend["sfcfsw"] = dict()
        Radtend["sfcflw"] = dict()

        Diag["fluxr"] = np.zeros((IM, 45))
        Diag["topflw"] = dict()
        Diag["topfsw"] = dict()
        Diag["topfsw"]["upfxc"] = np.zeros(IM)
        Diag["topfsw"]["dnfxc"] = np.zeros(IM)
        Diag["topfsw"]["upfx0"] = np.zeros(IM)
        Radtend["sfcfsw"]["upfxc"] = np.zeros(IM)
        Radtend["sfcfsw"]["dnfxc"] = np.zeros(IM)
        Radtend["sfcfsw"]["upfx0"] = np.zeros(IM)
        Radtend["sfcfsw"]["dnfx0"] = np.zeros(IM)
        Radtend["htrlw"] = np.zeros((IM, gfs_physics_control.config.levs))

        lhlwb = False
        lhlw0 = True
        lflxprf = False

        LMK = LM + self.LTP  # num of local layers
        LMP = LMK + 1  # num of local levels

        if self.lextop:
            if ivflip == 1:  # vertical from sfc upward
                kd = 0  # index diff between in/out and local
                kt = 1  # index diff between lyr and upper bound
                kb = 0  # index diff between lyr and lower bound
                lla = LMK  # local index at the 2nd level from top
                llb = LMP  # local index at toa level
                lya = LM  # local index for the 2nd layer from top
                lyb = LP1  # local index for the top layer
            else:  # vertical from toa downward
                kd = 1  # index diff between in/out and local
                kt = 0  # index diff between lyr and upper bound
                kb = 1  # index diff between lyr and lower bound
                lla = 2  # local index at the 2nd level from top
                llb = 1  # local index at toa level
                lya = 2  # local index for the 2nd layer from top
                lyb = 1  # local index for the top layer
        else:
            kd = 0
            if ivflip == 1:  # vertical from sfc upward
                kt = 1  # index diff between lyr and upper bound
                kb = 0  # index diff between lyr and lower bound
            else:  # vertical from toa downward
                kt = 0  # index diff between lyr and upper bound
                kb = 1  # index diff between lyr and lower bound

        raddt = min(gfs_physics_control.config.fhswr, gfs_physics_control.config.fhlwr)

        # -# Setup surface ground temperature and ground/air skin temperature
        # if required.

        if self.itsfc == 0:  # use same sfc skin-air/ground temp
            for i in range(IM):
                tskn[i] = Sfcprop["tsfc"][i]
                tsfg[i] = Sfcprop["tsfc"][i]
        else:  # use diff sfc skin-air/ground temp
            for i in range(IM):
                tskn[i] = Sfcprop["tsfc"][i]
                tsfg[i] = Sfcprop["tsfc"][i]

        # Prepare atmospheric profiles for radiation input.
        #
        lsk = 0
        if ivflip == 0 and LM < LEVS:
            lsk = LEVS - LM

        #           convert pressure unit from pa to mb
        k1 = np.arange(LM) + kd
        k2 = np.arange(LM) + lsk
        # for i in range(IM):
        plvl[:, k1 + kb] = Statein["prsi"][:, k2 + kb] * 0.01  # pa to mb (hpa)
        plyr[:, k1] = Statein["prsl"][:, k2] * 0.01  # pa to mb (hpa)
        tlyr[:, k1] = Statein["tgrs"][:, k2]
        prslk1[:, k1] = Statein["prslk"][:, k2]

        #  - Compute relative humidity.
        es = np.minimum(
            Statein["prsl"][:, k2], fpvs(Statein["tgrs"][:, k2])
        )  # fpvs and prsl in pa
        qs = np.maximum(
            self.QMIN, con_eps * es / (Statein["prsl"][:, k2] + con_epsm1 * es)
        )
        rhly[:, k1] = np.maximum(
            0.0, np.minimum(1.0, np.maximum(self.QMIN, Statein["qgrs"][:, k2, 0]) / qs)
        )
        qstl[:, k1] = qs
        # recast remaining all tracers (except sphum) forcing them all to be positive
        for j in range(1, NTRAC):
            for k in range(LM):
                k1 = k + kd
                k2 = k + lsk
                tracer1[:, k1, j] = np.maximum(0.0, Statein["qgrs"][:, k2, j])

        if ivflip == 0:  # input data from toa to sfc
            for i in range(IM):
                plvl[i, 1 + kd] = 0.01 * Statein["prsi"][i, 0]  # pa to mb (hpa)

            if lsk != 0:
                for i in range(IM):
                    plvl[i, 1 + kd] = 0.5 * (plvl[i, 2 + kd] + plvl[i, 1 + kd])
        else:  # input data from sfc to top
            for i in range(IM):
                plvl[i, LP1 + kd - 1] = (
                    0.01 * Statein["prsi"][i, LP1 + lsk - 1]
                )  # pa to mb (hpa)

            if lsk != 0:
                for i in range(IM):
                    plvl[i, LM + kd - 1] = 0.5 * (
                        plvl[i, LP1 + k - 1] + plvl[i, LM + kd - 1]
                    )

        if self.lextop:  # values for extra top layer
            for i in range(IM):
                plvl[i, llb - 1] = self.prsmin
                if plvl[i, lla - 1] <= self.prsmin:
                    plvl[i, lla - 1] = 2.0 * self.prsmin

                plyr[i, lyb - 1] = 0.5 * plvl[i, lla - 1]
                tlyr[i, lyb - 1] = tlyr[i, lya - 1]
                prslk1[i, lyb - 1] = (
                    plyr[i, lyb - 1] * 0.00001
                ) ** con_rocp  # plyr in Pa
                rhly[i, lyb - 1] = rhly[i, lya - 1]
                qstl[i, lyb - 1] = qstl[i, lya - 1]

            #  ---  note: may need to take care the top layer amount
            tracer1[:, lyb - 1, :] = tracer1[:, lya - 1, :]

        #  - Get layer ozone mass mixing ratio (if use ozone climatology data,
        #    call getozn()).

        if gfs_physics_control.ntoz > 0:  # interactive ozone generation
            for k in range(LMK):
                for i in range(IM):
                    olyr[i, k] = max(
                        self.QMIN, tracer1[i, k, gfs_physics_control.ntoz - 1]
                    )
        else:  # climatological ozone
            print("Climatological ozone not implemented")

        #  - Call coszmn(), to compute cosine of zenith angle (only when SW is called)

        if gfs_physics_control.lsswr:
            Radtend["coszen"], Radtend["coszdg"] = self.sol.coszmn(
                Grid["xlon"], Grid["sinlat"], Grid["coslat"], solhr, IM
            )

        #  - Call getgases(), to set up non-prognostic gas volume mixing
        #    ratioes (gasvmr).
        #  - gasvmr(:,:,1)  -  co2 volume mixing ratio
        #  - gasvmr(:,:,2)  -  n2o volume mixing ratio
        #  - gasvmr(:,:,3)  -  ch4 volume mixing ratio
        #  - gasvmr(:,:,4)  -  o2  volume mixing ratio
        #  - gasvmr(:,:,5)  -  co  volume mixing ratio
        #  - gasvmr(:,:,6)  -  cf11 volume mixing ratio
        #  - gasvmr(:,:,7)  -  cf12 volume mixing ratio
        #  - gasvmr(:,:,8)  -  cf22 volume mixing ratio
        #  - gasvmr(:,:,9)  -  ccl4 volume mixing ratio

        #  --- ...  set up non-prognostic gas volume mixing ratioes

        gasvmr = self.gas.getgases(plvl, Grid["xlon"], Grid["xlat"], IM, LMK,)

        #  - Get temperature at layer interface, and layer moisture.
        for k in range(1, LMK):
            for i in range(IM):
                tem2da[i, k] = np.log(plyr[i, k])
                tem2db[i, k] = np.log(plvl[i, k])

        if ivflip == 0:  # input data from toa to sfc
            for i in range(IM):
                tem1d[i] = self.QME6
                tem2da[i, 0] = np.log(plyr[i, 0])
                tem2db[i, 0] = np.log(max(self.prsmin, plvl[i, 0]))
                tem2db[i, LMP - 1] = np.log(plvl[i, LMP - 1])
                tsfa[i] = tlyr[i, LMK - 1]  # sfc layer air temp
                tlvl[i, 0] = tlyr[i, 0]
                tlvl[i, LMP - 1] = tskn[i]

            for k in range(LM):
                k1 = k + kd
                for i in range(IM):
                    qlyr[i, k1] = max(tem1d[i], Statein["qgrs"][i, k, 0])
                    tem1d[i] = min(self.QME5, qlyr[i, k1])
                    tvly[i, k1] = Statein.tgrs[i, k] * (
                        1.0 + con_fvirt * qlyr[i, k1]
                    )  # virtual T (K)
                    delp[i, k1] = plvl[i, k1 + 1] - plvl[i, k1]

            if self.lextop:
                for i in range(IM):
                    qlyr[i, lyb - 1] = qlyr[i, lya - 1]
                    tvly[i, lyb - 1] = tvly[i, lya - 1]
                    delp[i, lyb - 1] = plvl[i, lla - 1] - plvl[i, llb - 1]

            for k in range(1, LMK):
                for i in range(IM):
                    tlvl[i, k] = tlyr[i, k] + (tlyr[i, k - 1] - tlyr[i, k]) * (
                        tem2db[i, k] - tem2da[i, k]
                    ) / (tem2da[i, k - 1] - tem2da[i, k])

            #  ---  ...  level height and layer thickness (km)

            tem0d = 0.001 * con_rog
            for i in range(IM):
                for k in range(LMK):
                    dz[i, k] = tem0d * (tem2db[i, k + 1] - tem2db[i, k]) * tvly[i, k]
        else:

            for i in range(IM):
                tem1d[i] = self.QME6
                tem2da[i, 0] = np.log(plyr[i, 0])
                tem2db[i, 0] = np.log(plvl[i, 0])
                tem2db[i, LMP - 1] = np.log(max(self.prsmin, plvl[i, LMP - 1]))
                tsfa[i] = tlyr[i, 0]  # sfc layer air temp
                tlvl[i, 0] = tskn[i]
                tlvl[i, LMP - 1] = tlyr[i, LMK - 1]

            for k in range(LM - 1, -1, -1):
                for i in range(IM):
                    qlyr[i, k] = max(tem1d[i], Statein["qgrs"][i, k, 0])
                    tem1d[i] = min(self.QME5, qlyr[i, k])
                    tvly[i, k] = Statein["tgrs"][i, k] * (
                        1.0 + con_fvirt * qlyr[i, k]
                    )  # virtual T (K)
                    delp[i, k] = plvl[i, k] - plvl[i, k + 1]

            if self.lextop:
                for i in range(IM):
                    qlyr[i, lyb - 1] = qlyr[i, lya - 1]
                    tvly[i, lyb - 1] = tvly[i, lya - 1]
                    delp[i, lyb - 1] = plvl[i, lla - 1] - plvl[i, llb - 1]

            for k in range(LMK - 1):
                for i in range(IM):
                    tlvl[i, k + 1] = tlyr[i, k] + (tlyr[i, k + 1] - tlyr[i, k]) * (
                        tem2db[i, k + 1] - tem2da[i, k]
                    ) / (tem2da[i, k + 1] - tem2da[i, k])

            #  ---  ...  level height and layer thickness (km)

            tem0d = 0.001 * con_rog
            for i in range(IM):
                for k in range(LMK - 1, -1, -1):
                    dz[i, k] = tem0d * (tem2db[i, k] - tem2db[i, k + 1]) * tvly[i, k]

        #  - Check for daytime points for SW radiation.

        nday = 0
        for i in range(IM):
            if Radtend["coszen"][i] >= 0.0001:
                nday += 1
                idxday[nday - 1] = i + 1

        #  - Call module_radiation_aerosols::setaer(),to setup aerosols
        # property profile for radiation.

        faersw, faerlw, aerodp = self.aer.setaer(
            plvl,
            plyr,
            prslk1,
            tvly,
            rhly,
            Sfcprop["slmsk"],
            tracer1,
            Grid["xlon"],
            Grid["xlat"],
            IM,
            LMK,
            LMP,
            gfs_physics_control.lsswr,
            gfs_physics_control.lslwr,
        )

        #  - Obtain cloud information for radiation calculations
        #    (clouds,cldsa,mtopa,mbota)
        #     for  prognostic cloud:
        #    - For Zhao/Moorthi's prognostic cloud scheme,
        #      call module_radiation_clouds::progcld1()
        #    - For Zhao/Moorthi's prognostic cloud+pdfcld,
        #      call module_radiation_clouds::progcld3()
        #      call module_radiation_clouds::progclduni() for unified cloud and ncld=2

        #  --- ...  obtain cloud information for radiation calculations

        if gfs_physics_control.config.ncnd == 1:  # Zhao_Carr_Sundqvist
            for k in range(LMK):
                for i in range(IM):
                    ccnd[i, k, 0] = tracer1[i, k, ntcw - 1]  # liquid water/ice
        elif gfs_physics_control.config.ncnd == 2:  # MG
            for k in range(LMK):
                for i in range(IM):
                    ccnd[i, k, 0] = tracer1[i, k, ntcw - 1]  # liquid water
                    ccnd[i, k, 1] = tracer1[i, k, ntiw - 1]  # ice water
        elif gfs_physics_control.config.ncnd == 4:  # MG2
            for k in range(LMK):
                for i in range(IM):
                    ccnd[i, k, 0] = tracer1[i, k, ntcw - 1]  # liquid water
                    ccnd[i, k, 1] = tracer1[i, k, ntiw - 1]  # ice water
                    ccnd[i, k, 2] = tracer1[i, k, ntrw - 1]  # rain water
                    ccnd[i, k, 3] = tracer1[i, k, ntsw - 1]  # snow water
        elif gfs_physics_control.config.ncnd == 5:  # GFDL MP, Thompson, MG3
            for k in range(LMK):
                for i in range(IM):
                    ccnd[i, k, 0] = tracer1[i, k, ntcw - 1]  # liquid water
                    ccnd[i, k, 1] = tracer1[i, k, ntiw - 1]  # ice water
                    ccnd[i, k, 2] = tracer1[i, k, ntrw - 1]  # rain water
                    ccnd[i, k, 3] = (
                        tracer1[i, k, ntsw - 1] + tracer1[i, k, ntgl - 1]
                    )  # snow + grapuel

        for n in range(ncndl):
            for k in range(LMK):
                for i in range(IM):
                    if ccnd[i, k, n] < con_epsq:
                        ccnd[i, k, n] = 0.0

        if gfs_physics_control.config.imp_physics == 11:
            if not gfs_physics_control.config.lgfdlmprad:

                # rsun the  summation methods and
                # order make the difference in calculation
                ccnd[:, :, 0] = tracer1[:, :LMK, ntcw - 1]
                ccnd[:, :, 0] = ccnd[:, :, 0] + tracer1[:, :LMK, ntrw - 1]
                ccnd[:, :, 0] = ccnd[:, :, 0] + tracer1[:, :LMK, ntiw - 1]
                ccnd[:, :, 0] = ccnd[:, :, 0] + tracer1[:, :LMK, ntsw - 1]
                ccnd[:, :, 0] = ccnd[:, :, 0] + tracer1[:, :LMK, ntgl - 1]

            for k in range(LMK):
                for i in range(IM):
                    if ccnd[i, k, 0] < self.EPSQ:
                        ccnd[i, k, 0] = 0.0

        if gfs_physics_control.config.imp_physics == 11:  # GFDL MP
            cldcov[:IM, kd : LM + kd] = tracer1[
                :IM, :LM, gfs_physics_control.ntclamt - 1
            ]

        else:  # neither of the other two cases
            cldcov = 0.0

        #  --- add suspended convective cloud water to grid-scale cloud water
        #      only for cloud fraction & radiation computation
        #      it is to enhance cloudiness due to suspended convec cloud water
        #      for zhao/moorthi's (imp_phys=99) &
        #          ferrier's (imp_phys=5) microphysics schemes

        if (
            gfs_physics_control.config.num_p3d == 1
            and gfs_physics_control.config.npdf3d == 0
            and gfs_physics_control.config.ncnvcld3d == 0
        ):  # all the rest
            for k in range(LMK):
                for i in range(IM):
                    deltaq[i, k] = 0.0
                    cnvw[i, k] = 0.0
                    cnvc[i, k] = 0.0

        if self.lextop:
            for i in range(IM):
                cldcov[i, lyb - 1] = cldcov[i, lya - 1]
                deltaq[i, lyb - 1] = deltaq[i, lya - 1]
                cnvw[i, lyb - 1] = cnvw[i, lya - 1]
                cnvc[i, lyb - 1] = cnvc[i, lya - 1]

        if gfs_physics_control.config.imp_physics == 99:
            ccnd[:IM, :LMK, 0] = ccnd[:IM, :LMK, 0] + cnvw[:IM, :LMK]

        clouds, cldsa, mtopa, mbota, de_lgth = self.cld.progcld4(
            plyr,
            plvl,
            tlyr,
            tvly,
            qlyr,
            qstl,
            rhly,
            ccnd[:IM, :LMK, 0],
            cnvw,
            cnvc,
            Grid["xlat"],
            Grid["xlon"],
            Sfcprop["slmsk"],
            cldcov,
            dz,
            delp,
            IM,
            LMK,
            LMP,
        )

        #  --- ...  start radiation calculations
        #           remember to set heating rate unit to k/sec!

        # mg, sfc-perts
        #  ---  scale random patterns for surface perturbations with
        #  perturbation size
        #  ---  turn vegetation fraction pattern into percentile pattern

        if gfs_physics_control.config.do_sfcperts:
            print("Surface perturbation not implemented!")

        # mg, sfc-perts

        if gfs_physics_control.config.do_only_clearsky_rad:
            clouds[:, :, 0] = 0.0  # layer total cloud fraction
            clouds[:, :, 1] = 0.0  # layer cloud liq water path
            clouds[:, :, 3] = 0.0  # layer cloud ice water path
            clouds[:, :, 5] = 0.0  # layer rain water path
            clouds[:, :, 7] = 0.0  # layer snow water path
            cldsa[:, :] = 0.0  # fraction of clouds for low, mid, hi, tot, bl

        # Start SW radiation calculations
        if gfs_physics_control.lsswr:

            #  - Call module_radiation_surface::setalb() to setup surface albedo.
            #  for SW radiation.

            sfcalb = self.sfc.setalb(
                Sfcprop["slmsk"],
                Sfcprop["snowd"],
                Sfcprop["sncovr"],
                Sfcprop["snoalb"],
                Sfcprop["zorl"],
                Radtend["coszen"],
                tsfg,
                tsfa,
                Sfcprop["hprime"],
                Sfcprop["alvsf"],
                Sfcprop["alnsf"],
                Sfcprop["alvwf"],
                Sfcprop["alnwf"],
                Sfcprop["facsf"],
                Sfcprop["facwf"],
                Sfcprop["fice"],
                Sfcprop["tisfc"],
                IM,
                alb1d,
                gfs_physics_control.config.pertalb,
            )

            # Approximate mean surface albedo from vis- and nir-  diffuse values.
            Radtend["sfalb"] = np.maximum(0.01, 0.5 * (sfcalb[:, 1] + sfcalb[:, 3]))

            lhswb = False
            lhsw0 = True
            lflxprf = False
            lfdncmp = True

            if nday > 0:

                #  - Call module_radsw_main::swrad(), to compute SW heating rates and
                #   fluxes.

                if gfs_physics_control.config.swhtr:
                    (
                        htswc,
                        Diag["topfsw"]["upfxc"],
                        Diag["topfsw"]["dnfxc"],
                        Diag["topfsw"]["upfx0"],
                        Radtend["sfcfsw"]["upfxc"],
                        Radtend["sfcfsw"]["dnfxc"],
                        Radtend["sfcfsw"]["upfx0"],
                        Radtend["sfcfsw"]["dnfx0"],
                        cldtausw,
                        htsw0,
                        scmpsw["uvbf0"],
                        scmpsw["uvbfc"],
                        scmpsw["nirbm"],
                        scmpsw["nirdf"],
                        scmpsw["visbm"],
                        scmpsw["visdf"],
                    ) = self.rsw.swrad(
                        plyr,
                        plvl,
                        tlyr,
                        tlvl,
                        qlyr,
                        olyr,
                        gasvmr,
                        clouds,
                        faersw,
                        sfcalb,
                        dz,
                        delp,
                        de_lgth,
                        Radtend["coszen"],
                        solcon,
                        nday,
                        idxday,
                        IM,
                        LMK,
                        LMP,
                        gfs_physics_control.config.lprnt,
                        lhswb,
                        lhsw0,
                        lflxprf,
                        lfdncmp,
                        randomdict["sw_rand"],
                        swdict,
                    )
                else:
                    (
                        htswc,
                        Diag["topfsw"]["upfxc"],
                        Diag["topfsw"]["dnfxc"],
                        Diag["topfsw"]["upfx0"],
                        Radtend["sfcfsw"]["upfxc"],
                        Radtend["sfcfsw"]["dnfxc"],
                        Radtend["sfcfsw"]["upfx0"],
                        Radtend["sfcfsw"]["dnfx0"],
                        cldtausw,
                        scmpsw["uvbf0"],
                        scmpsw["uvbfc"],
                        scmpsw["nirbm"],
                        scmpsw["nirdf"],
                        scmpsw["visbm"],
                        scmpsw["visdf"],
                    ) = self.rsw.swrad(
                        plyr,
                        plvl,
                        tlyr,
                        tlvl,
                        qlyr,
                        olyr,
                        gasvmr,
                        clouds,
                        faersw,
                        sfcalb,
                        dz,
                        delp,
                        de_lgth,
                        Radtend["coszen"],
                        solcon,
                        nday,
                        idxday,
                        IM,
                        LMK,
                        LMP,
                        gfs_physics_control.config.lprnt,
                        lhswb,
                        lhsw0,
                        lflxprf,
                        lfdncmp,
                        randomdict["sw_rand"],
                        swdict,
                    )

                for k in range(LM):
                    k1 = k + kd
                    Radtend["htrsw"][:IM, k] = htswc[:IM, k1]

                #     We are assuming that radiative tendencies are from bottom to top
                # --- repopulate the points above levr i.e. LM
                if LM < LEVS:
                    for k in range(LM, LEVS):
                        Radtend["htrsw"][:IM, k] = Radtend["htrsw"][:IM, LM - 1]

                if gfs_physics_control.config.swhtr:
                    for k in range(LM):
                        k1 = k + kd
                        Radtend["swhc"][:IM, k] = htsw0[:IM, k1]

                    # --- repopulate the points above levr i.e. LM
                    if LM < LEVS:
                        for k in range(LM, LEVS):
                            Radtend["swhc"][:IM, k] = Radtend["swhc"][:IM, LM - 1]

                #  --- surface down and up spectral component fluxes
                #  - Save two spectral bands' surface downward and upward fluxes for
                #    output.

                Coupling["nirbmdi"] = scmpsw["nirbm"]
                Coupling["nirdfdi"] = scmpsw["nirdf"]
                Coupling["visbmdi"] = scmpsw["visbm"]
                Coupling["visdfdi"] = scmpsw["visdf"]

                Coupling["nirbmui"] = scmpsw["nirbm"] * sfcalb[:, 0]
                Coupling["nirdfui"] = scmpsw["nirdf"] * sfcalb[:, 1]
                Coupling["visbmui"] = scmpsw["visbm"] * sfcalb[:, 2]
                Coupling["visdfui"] = scmpsw["visdf"] * sfcalb[:, 3]

            else:

                Radtend["htrsw"][:, :] = 0.0
                Coupling["nirbmdi"] = np.zeros(IM)
                Coupling["nirdfdi"] = np.zeros(IM)
                Coupling["visbmdi"] = np.zeros(IM)
                Coupling["visdfdi"] = np.zeros(IM)
                Coupling["nirbmui"] = np.zeros(IM)
                Coupling["nirdfui"] = np.zeros(IM)
                Coupling["visbmui"] = np.zeros(IM)
                Coupling["visdfui"] = np.zeros(IM)

                if gfs_physics_control.config.swhtr:
                    Radtend["swhc"][:, :] = 0
                    cldtausw[:, :] = 0.0

            # --- radiation fluxes for other physics processes
            Coupling["sfcnsw"] = Radtend["sfcfsw"]["dnfxc"] - Radtend["sfcfsw"]["upfxc"]
            Coupling["sfcdsw"] = Radtend["sfcfsw"]["dnfxc"]

        # Start LW radiation calculations
        if gfs_physics_control.lslwr:

            #  - Call module_radiation_surface::setemis(),to setup surface
            # emissivity for LW radiation.

            Radtend["semis"] = self.sfc.setemis(
                Grid["xlon"],
                Grid["xlat"],
                Sfcprop["slmsk"],
                Sfcprop["snowd"],
                Sfcprop["sncovr"],
                Sfcprop["zorl"],
                tsfg,
                tsfa,
                Sfcprop["hprime"],
                IM,
            )

            #  - Call module_radlw_main::lwrad(), to compute LW heating rates and
            #    fluxes.

            if gfs_physics_control.config.lwhtr:
                (
                    htlwc,
                    Diag["topflw"]["upfxc"],
                    Diag["topflw"]["upfx0"],
                    Radtend["sfcflw"]["upfxc"],
                    Radtend["sfcflw"]["upfx0"],
                    Radtend["sfcflw"]["dnfxc"],
                    Radtend["sfcflw"]["dnfx0"],
                    cldtaulw,
                    htlw0,
                ) = self.rlw.lwrad(
                    plyr,
                    plvl,
                    tlyr,
                    tlvl,
                    qlyr,
                    olyr,
                    gasvmr,
                    clouds,
                    faerlw,
                    Radtend["semis"],
                    tsfg,
                    dz,
                    delp,
                    de_lgth,
                    IM,
                    LMK,
                    LMP,
                    gfs_physics_control.config.lprnt,
                    lhlwb,
                    lhlw0,
                    lflxprf,
                    randomdict["lw_rand"],
                    lwdict,
                )
            else:
                (
                    htlwc,
                    Diag["topflw"]["upfxc"],
                    Diag["topflw"]["upfx0"],
                    Radtend["sfcflw"]["upfxc"],
                    Radtend["sfcflw"]["upfx0"],
                    Radtend["sfcflw"]["dnfxc"],
                    Radtend["sfcflw"]["dnfx0"],
                    cldtaulw,
                ) = self.rlw.lwrad(
                    plyr,
                    plvl,
                    tlyr,
                    tlvl,
                    qlyr,
                    olyr,
                    gasvmr,
                    clouds,
                    faerlw,
                    Radtend["semis"],
                    tsfg,
                    dz,
                    delp,
                    de_lgth,
                    IM,
                    LMK,
                    LMP,
                    gfs_physics_control.config.lprnt,
                    lhlwb,
                    lhlw0,
                    lflxprf,
                    randomdict["lw_rand"],
                    lwdict,
                )

            # Save calculation results
            #  - Save surface air temp for diurnal adjustment at model t-steps
            Radtend["tsflw"][:] = tsfa[:]

            for k in range(LM):
                k1 = k + kd
                Radtend["htrlw"][:IM, k] = htlwc[:IM, k1]

            # --- repopulate the points above levr
            if LM < LEVS:
                for k in range(LM, LEVS):
                    Radtend["htrlw"][IM, k] = Radtend["htrlw"][:IM, LM - 1]

            if gfs_physics_control.config.lwhtr:
                for k in range(LM):
                    k1 = k + kd
                    Radtend["lwhc"][:IM, k] = htlw0[:IM, k1]

                # --- repopulate the points above levr
                if LM < LEVS:
                    for k in range(LM, LEVS):
                        Radtend["lwhc"][:IM, k] = Radtend["lwhc"][:IM, LM - 1]

            # --- radiation fluxes for other physics processes
            Coupling["sfcdlw"] = Radtend["sfcflw"]["dnfxc"]

        #  - For time averaged output quantities (including total-sky and
        #    clear-sky SW and LW fluxes at TOA and surface; conventional
        #    3-domain cloud amount, cloud top and base pressure, and cloud top
        #    temperature; aerosols AOD, etc.), store computed results in
        #    corresponding slots of array fluxr with appropriate time weights.

        #  --- ...  collect the fluxr data for wrtsfc

        if gfs_physics_control.config.lssav:
            if gfs_physics_control.lsswr:
                for i in range(IM):
                    Diag["fluxr"][i, 33] = (
                        Diag["fluxr"][i, 33]
                        + gfs_physics_control.config.fhswr * aerodp[i, 0]
                    )  # total aod at 550nm
                    Diag["fluxr"][i, 34] = (
                        Diag["fluxr"][i, 34]
                        + gfs_physics_control.config.fhswr * aerodp[i, 1]
                    )  # DU aod at 550nm
                    Diag["fluxr"][i, 35] = (
                        Diag["fluxr"][i, 35]
                        + gfs_physics_control.config.fhswr * aerodp[i, 2]
                    )  # BC aod at 550nm
                    Diag["fluxr"][i, 36] = (
                        Diag["fluxr"][i, 36]
                        + gfs_physics_control.config.fhswr * aerodp[i, 3]
                    )  # OC aod at 550nm
                    Diag["fluxr"][i, 37] = (
                        Diag["fluxr"][i, 37]
                        + gfs_physics_control.config.fhswr * aerodp[i, 4]
                    )  # SU aod at 550nm
                    Diag["fluxr"][i, 38] = (
                        Diag["fluxr"][i, 38]
                        + gfs_physics_control.config.fhswr * aerodp[i, 5]
                    )  # SS aod at 550nm

            #  ---  save lw toa and sfc fluxes
            if gfs_physics_control.lslwr:
                #  ---  lw total-sky fluxes
                for i in range(IM):
                    Diag["fluxr"][i, 0] = (
                        Diag["fluxr"][i, 0]
                        + gfs_physics_control.config.fhlwr * Diag["topflw"]["upfxc"][i]
                    )  # total sky top lw up
                    Diag["fluxr"][i, 18] = (
                        Diag["fluxr"][i, 18]
                        + gfs_physics_control.config.fhlwr
                        * Radtend["sfcflw"]["dnfxc"][i]
                    )  # total sky sfc lw dn
                    Diag["fluxr"][i, 19] = (
                        Diag["fluxr"][i, 19]
                        + gfs_physics_control.config.fhlwr
                        * Radtend["sfcflw"]["upfxc"][i]
                    )  # total sky sfc lw up
                    #  ---  lw clear-sky fluxes
                    Diag["fluxr"][i, 27] = (
                        Diag["fluxr"][i, 27]
                        + gfs_physics_control.config.fhlwr * Diag["topflw"]["upfx0"][i]
                    )  # clear sky top lw up
                    Diag["fluxr"][i, 29] = (
                        Diag["fluxr"][i, 29]
                        + gfs_physics_control.config.fhlwr
                        * Radtend["sfcflw"]["dnfx0"][i]
                    )  # clear sky sfc lw dn
                    Diag["fluxr"][i, 32] = (
                        Diag["fluxr"][i, 32]
                        + gfs_physics_control.config.fhlwr
                        * Radtend["sfcflw"]["upfx0"][i]
                    )  # clear sky sfc lw up

            # save sw toa and sfc fluxes with proper diurnal sw wgt.
            # coszen=mean cosz over daylight
            # part of sw calling interval, while coszdg= mean
            # cosz over entire interval
            if gfs_physics_control.lsswr:
                for i in range(IM):
                    if Radtend["coszen"][i] > 0.0:
                        #  --- sw total-sky fluxes
                        #      -------------------
                        tem0d = (
                            gfs_physics_control.config.fhswr
                            * Radtend["coszdg"][i]
                            / Radtend["coszen"][i]
                        )
                        Diag["fluxr"][i, 1] = (
                            Diag["fluxr"][i, 1] + Diag["topfsw"]["upfxc"][i] * tem0d
                        )  # total sky top sw up
                        Diag["fluxr"][i, 2] = (
                            Diag["fluxr"][i, 2] + Radtend["sfcfsw"]["upfxc"][i] * tem0d
                        )  # total sky sfc sw up
                        Diag["fluxr"][i, 3] = (
                            Diag["fluxr"][i, 4] + Radtend["sfcfsw"]["dnfxc"][i] * tem0d
                        )  # total sky sfc sw dn
                        #  --- sw uv-b fluxes
                        #      --------------
                        Diag["fluxr"][i, 20] = (
                            Diag["fluxr"][i, 20] + scmpsw["uvbfc"][i] * tem0d
                        )  # total sky uv-b sw dn
                        Diag["fluxr"][i, 21] = (
                            Diag["fluxr"][i, 21] + scmpsw["uvbf0"][i] * tem0d
                        )  # clear sky uv-b sw dn
                        #  --- sw toa incoming fluxes
                        #      ----------------------
                        Diag["fluxr"][i, 22] = (
                            Diag["fluxr"][i, 22] + Diag["topfsw"]["dnfxc"][i] * tem0d
                        )  # top sw dn
                        #  --- sw sfc flux components
                        #      ----------------------
                        Diag["fluxr"][i, 23] = (
                            Diag["fluxr"][i, 23] + scmpsw["visbm"][i] * tem0d
                        )  # uv/vis beam sw dn
                        Diag["fluxr"][i, 24] = (
                            Diag["fluxr"][i, 24] + scmpsw["visdf"][i] * tem0d
                        )  # uv/vis diff sw dn
                        Diag["fluxr"][i, 25] = (
                            Diag["fluxr"][i, 25] + scmpsw["nirbm"][i] * tem0d
                        )  # nir beam sw dn
                        Diag["fluxr"][i, 26] = (
                            Diag["fluxr"][i, 26] + scmpsw["nirdf"][i] * tem0d
                        )  # nir diff sw dn
                        #  --- sw clear-sky fluxes
                        #      -------------------
                        Diag["fluxr"][i, 28] = (
                            Diag["fluxr"][i, 28] + Diag["topfsw"]["upfx0"][i] * tem0d
                        )  # clear sky top sw up
                        Diag["fluxr"][i, 30] = (
                            Diag["fluxr"][i, 30] + Radtend["sfcfsw"]["upfx0"][i] * tem0d
                        )  # clear sky sfc sw up
                        Diag["fluxr"][i, 31] = (
                            Diag["fluxr"][i, 31] + Radtend["sfcfsw"]["dnfx0"][i] * tem0d
                        )  # clear sky sfc sw dn

            #  ---  save total and boundary layer clouds

            if gfs_physics_control.lsswr or gfs_physics_control.lslwr:
                for i in range(IM):
                    Diag["fluxr"][i, 16] = Diag["fluxr"][i, 16] + raddt * cldsa[i, 3]
                    Diag["fluxr"][i, 17] = Diag["fluxr"][i, 17] + raddt * cldsa[i, 4]

                #  ---  save cld frac,toplyr,botlyr and top temp, note that the order
                #       of h,m,l cloud is reversed for the fluxr output.
                #  ---  save interface pressure (pa) of top/bot

                for j in range(3):
                    for i in range(IM):
                        tem0d = raddt * cldsa[i, j]
                        itop = int(mtopa[i, j] - kd)
                        ibtc = int(mbota[i, j] - kd)
                        Diag["fluxr"][i, 6 - j] = Diag["fluxr"][i, 6 - j] + tem0d
                        Diag["fluxr"][i, 9 - j] = (
                            Diag["fluxr"][i, 9 - j]
                            + tem0d * Statein["prsi"][i, itop + kt - 1]
                        )
                        Diag["fluxr"][i, 12 - j] = (
                            Diag["fluxr"][i, 12 - j]
                            + tem0d * Statein["prsi"][i, ibtc + kb - 1]
                        )
                        Diag["fluxr"][i, 15 - j] = (
                            Diag["fluxr"][i, 15 - j]
                            + tem0d * Statein["tgrs"][i, itop - 1]
                        )

                        # Anning adds optical depth and emissivity output
                        tem1 = 0.0
                        tem2 = 0.0
                        for k in range(ibtc - 1, itop):
                            tem1 = tem1 + cldtausw[i, k]  # approx .55 mu channel
                            tem2 = tem2 + cldtaulw[i, k]  # approx 10. mu channel

                        Diag["fluxr"][i, 41 - j] = (
                            Diag["fluxr"][i, 41 - j] + tem0d * tem1
                        )
                        Diag["fluxr"][i, 44 - j] = Diag["fluxr"][i, 44 - j] + tem0d * (
                            1.0 - np.exp(-tem2)
                        )

        return Radtend, Diag, Coupling
