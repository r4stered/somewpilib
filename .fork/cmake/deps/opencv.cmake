# OpenCV (#33): stock opencv/opencv, built and installed by the provider.
#
# OpenCV is not one of the libraries upstream vendors. The carried
# CMakeLists.txt and tools/wpical both call find_package(OpenCV REQUIRED), so
# this recipe answers those calls through the provider instead of wiring
# anything in behind upstream's back. OpenCV is also the one external dependency
# that is public in an installed WPILib package -- the cscore and cameraserver
# configs call find_dependency(OpenCV) -- so it is installed into WPILib's own
# prefix, where those configs find it again (#5, #9). A build with cscore off
# and wpical on installs it too, which nothing there needs; it only costs disk.
#
# OpenCV makes a poor subproject (opencv/opencv#20548), so it is a configure-time
# sub-build like every other dependency, through wpilib_stock_build().

include_guard(GLOBAL)

# Builds OpenCV, the first time this is called, and sets <prefix_var> to the
# prefix it installed into.
function(_wpilib_opencv_build prefix_var)
    get_property(prefix GLOBAL PROPERTY _WPILIB_OPENCV_PREFIX)
    if(NOT prefix)
        wpilib_stock_build(opencv prefix
            GIT_REPOSITORY https://github.com/opencv/opencv.git
            # The version upstream builds (#5). OpenCV has no
            # upstream_utils/opencv.py to read a tag from, and no upstream tag
            # for a pin-table entry to override, so the default lives here.
            DEFAULT_TAG 4.13.0
            # WPILib's option set (#5), as defaults;
            # -DWPILIB_DEP_OPENCV_CMAKE_ARGS=... is appended after them.
            CMAKE_ARGS
                # Only the modules cscore and wpical use. OpenCV adds whatever
                # those depend on by itself.
                -DBUILD_LIST=core,imgproc,imgcodecs,videoio,highgui,objdetect,calib3d
                # The libraries and nothing else.
                -DBUILD_opencv_apps=OFF
                -DBUILD_DOCS=OFF
                -DBUILD_EXAMPLES=OFF
                -DBUILD_PERF_TESTS=OFF
                -DBUILD_TESTS=OFF
                -DBUILD_JAVA=OFF
                # Bundled image codecs, so none of them comes from the system.
                -DBUILD_ZLIB=ON
                -DBUILD_JPEG=ON
                -DBUILD_PNG=ON
                -DBUILD_OPENJPEG=ON
                # Backends and codecs WPILib doesn't use, off explicitly so
                # that whatever happens to be installed on the machine can't
                # change what gets built. Upstream's own build turns the same
                # ones off (#5). cscore reads cameras itself. WITH_EIGEN only
                # gates OpenCV's internal Eigen use: opencv2/core/eigen.hpp,
                # which is what wpical includes, is installed either way, and
                # its eigen2cv/cv2eigen compile and run against this build.
                -DWITH_FFMPEG=OFF
                -DWITH_GSTREAMER=OFF
                -DWITH_GTK=OFF
                -DWITH_QT=OFF
                -DWITH_CUDA=OFF
                -DWITH_IPP=OFF
                -DWITH_OPENCL=OFF
                -DWITH_LAPACK=OFF
                -DWITH_EIGEN=OFF
                -DWITH_PROTOBUF=OFF
                -DWITH_TIFF=OFF
                -DWITH_WEBP=OFF
                -DWITH_OPENEXR=OFF
                -DWITH_1394=OFF
                # G-API isn't in BUILD_LIST, but WITH_ADE is on by default, so
                # OpenCV downloads and builds ade anyway, then exports an `ade`
                # imported target whose library it never installs -- which
                # fails find_package(OpenCV) on the installed prefix.
                -DWITH_ADE=OFF
                # The script it would otherwise write hard-codes the build-tree
                # prefix, which is wrong once the prefix is installed elsewhere.
                -DOPENCV_GENERATE_SETUPVARS=OFF
        )
        set_property(GLOBAL PROPERTY _WPILIB_OPENCV_PREFIX "${prefix}")
    endif()
    set(${prefix_var} "${prefix}" PARENT_SCOPE)
endfunction()

# Answers find_package(OpenCV) with the prefix above. A macro, because
# cscore/CMakeLists.txt reads ${OpenCV_INCLUDE_DIRS} and the imported
# opencv_* targets have to land in the scope that asked for them.
#
# WPILIB_DEP_OPENCV_USE_SYSTEM leaves OpenCV_FOUND unset instead, which hands
# the call back to CMake's own search, i.e. to an installed OpenCV.
macro(_wpilib_provide_OpenCV)
    option(
        WPILIB_DEP_OPENCV_USE_SYSTEM
        "Use an installed OpenCV instead of building one from source."
        OFF
    )
    if(NOT WPILIB_DEP_OPENCV_USE_SYSTEM)
        _wpilib_opencv_build(_wpilib_opencv_prefix)
        find_package(
            OpenCV ${ARGN}
            CONFIG
            BYPASS_PROVIDER
            PATHS "${_wpilib_opencv_prefix}"
            NO_DEFAULT_PATH
        )
    endif()
endmacro()
