(function () {
    'use strict';

    angular.module('scaleApp').service('stateService', function ($location) {
        var queryString = $location.search(),
            user = {},
            version = '',
            jobsColDefs = [],
            jobsParams = {
                page: queryString.page ? parseInt(queryString.page) : 1,
                page_size: queryString.page_size ? parseInt(queryString.page_size) : 25,
                started: queryString.started ? queryString.started : moment.utc().subtract(1, 'weeks').startOf('d').toISOString(),
                ended: queryString.ended ? queryString.ended : moment.utc().endOf('d').toISOString(),
                order: queryString.order ? Array.isArray(queryString.order) ? queryString.order : [queryString.order] : ['-last_modified'],
                status: queryString.status ? queryString.status : null,
                error_category: queryString.error_category ? queryString.error_category : null,
                job_type_id: queryString.job_type_id ? parseInt(queryString.job_type_id) : null,
                job_type_name: queryString.job_type_name ? queryString.job_type_name : null,
                job_type_category: queryString.job_type_category ? queryString.job_type_category : null,
                url: null
            };

        return {
            getUser: function () {
                return user;
            },
            setUser: function (data) {
                user = data;
            },
            getVersion: function () {
                return version;
            },
            setVersion: function (data) {
                version = data;
            },
            getJobsColDefs: function () {
                return jobsColDefs;
            },
            setJobsColDefs: function (data) {
                jobsColDefs = data;
            },
            getJobsParams: function () {
                return jobsParams;
            },
            setJobsParams: function (data) {
                // check for jobsParams in query string, and update as necessary
                _.forEach(_.pairs(data), function (param) {
                    $location.search(param[0], param[1]);
                });
                jobsParams = data;
            }
        };
    });
})();
